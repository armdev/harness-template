# One-shot image for shared tooling (service-keys). Services build their own image on top of the same lib.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY libs/common /libs/common
RUN pip install --no-cache-dir /libs/common
ENTRYPOINT ["python", "-m", "common.keygen"]
