"""Kafka event consumer with the delivery semantics every air-harness consumer needs (rubric R8).

  consumer = EventConsumer("content.post.created", handle, bootstrap=os.environ["KAFKA_BOOTSTRAP"], group_id="search")
  consumer.start()   # in the service's lifespan; consumer.stop() on shutdown

- at-least-once: the offset is committed only after `handler(event)` returned; make the handler idempotent
  (upsert / ON CONFLICT) so a redelivered event is harmless;
- malformed events (not JSON, or the handler raises ValueError / KeyError) are logged and skipped — committed,
  because retrying can never fix them;
- any other handler error (e.g. the database is down) seeks back to the same offset and backs off, so the same
  event is delivered again; nothing is lost and nothing is skipped.

Needs the `kafka` extra of air-harness-common (confluent-kafka).
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from confluent_kafka import Consumer, KafkaError, TopicPartition

log = logging.getLogger(__name__)


class EventConsumer:
    def __init__(self, topic: str, handler: Callable[[dict], Any], *, bootstrap: str | None = None,
                 group_id: str | None = None, name: str = "consumer", backoff: float = 2.0,
                 consumer: Any = None):
        if consumer is None and not (bootstrap and group_id):
            raise ValueError("EventConsumer needs bootstrap and group_id (or a consumer for tests)")
        self.topic, self.handler, self.backoff = topic, handler, backoff
        self.config = {"bootstrap.servers": bootstrap, "group.id": group_id,
                       "auto.offset.reset": "earliest", "enable.auto.commit": False}
        self.consumer = consumer
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        if self.consumer is None:
            self.consumer = Consumer(self.config)
        self.consumer.subscribe([self.topic])
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=10)
        if self.consumer is not None:
            self.consumer.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()

    def poll_once(self) -> None:
        """Handle at most one message (public so tests can drive the loop step by step)."""
        msg = self.consumer.poll(1.0)
        if msg is None:
            return
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                log.warning("kafka: %s", msg.error())
            return
        try:
            self.handler(json.loads(msg.value()))
        except (ValueError, KeyError) as e:
            log.error("skipping malformed event at offset %s: %s", msg.offset(), e)
        except Exception:
            log.exception("handling failed at offset %s; will retry", msg.offset())
            self.consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))
            self._stop.wait(self.backoff)                # e.g. database down: back off, then redeliver
            return
        self.consumer.commit(message=msg, asynchronous=False)
