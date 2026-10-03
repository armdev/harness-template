"""Kafka consumer that records one notification per content.post.created event.

At-least-once: the offset is committed only after the row is written; post_id is the primary key and the insert
does nothing on conflict, so a redelivered event never notifies twice.
"""
from __future__ import annotations

import json
import logging
import threading

from confluent_kafka import Consumer, KafkaError, TopicPartition
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

INSERT = """
INSERT INTO notify.outbox (post_id, author, created_at)
VALUES (%(id)s, %(author)s, %(created_at)s)
ON CONFLICT (post_id) DO NOTHING
"""


class Notifier:
    def __init__(self, pool: ConnectionPool, bootstrap: str, topic: str):
        self.pool, self.topic = pool, topic
        self.consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "notify",
                                  "auto.offset.reset": "earliest", "enable.auto.commit": False})
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)

    def start(self) -> None:
        self.consumer.subscribe([self.topic])
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        self.consumer.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            msg = self.consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.warning("kafka: %s", msg.error())
                continue
            try:
                event = json.loads(msg.value())
                with self.pool.connection() as conn:
                    conn.execute(INSERT, event)
            except (ValueError, KeyError) as e:
                log.error("skipping malformed event at offset %s: %s", msg.offset(), e)
            except Exception:
                log.exception("recording failed at offset %s; will retry", msg.offset())
                self.consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))
                self._stop.wait(2)                # database down: back off, then redeliver the same event
                continue
            self.consumer.commit(message=msg, asynchronous=False)
