"""Logging, request ids and Prometheus metrics, wired the same way in every service.

  app = create_app("content", lifespan=lifespan)

gives JSON logs on stdout (level from LOG_LEVEL, every line carries the request id), GET /healthz,
GET /metrics and the http_requests_total / http_request_duration_seconds series the alert rules use.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
import uuid

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_ID_HEADER = "X-Request-ID"
request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

REQUESTS = Counter("http_requests_total", "HTTP requests", ["service", "method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["service", "method", "route"])


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        line = {"ts": round(record.created, 3), "level": record.levelname, "service": self.service,
                "logger": record.name, "msg": record.getMessage(), "request_id": request_id.get()}
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False)


def setup_logging(service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    logging.getLogger("uvicorn.access").disabled = True   # the metrics middleware covers access


def create_app(service: str, **fastapi_kwargs) -> FastAPI:
    setup_logging(service)
    app = FastAPI(title=service, **fastapi_kwargs)

    @app.middleware("http")
    async def observe(request: Request, call_next):
        token = request_id.set(request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id.get() or ""
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if route not in ("/metrics", "/healthz"):
                REQUESTS.labels(service, request.method, route, str(status)).inc()
                LATENCY.labels(service, request.method, route).observe(time.perf_counter() - t0)
            request_id.reset(token)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", "service": service}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
