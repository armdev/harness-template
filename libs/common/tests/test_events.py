"""EventConsumer semantics: commit only after the handler succeeded; skip malformed events; retry the same
offset when the handler fails for another reason."""
import json

import pytest
from confluent_kafka import KafkaError

from common.events import EventConsumer


class Msg:
    def __init__(self, value, offset, error=None, partition=0, topic="t"):
        self._value, self._offset, self._error, self._partition, self._topic = value, offset, error, partition, topic

    def value(self):
        return self._value

    def offset(self):
        return self._offset

    def error(self):
        return self._error

    def partition(self):
        return self._partition

    def topic(self):
        return self._topic


class Err:
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code


class FakeConsumer:
    def __init__(self, messages):
        self.queue = list(messages)
        self.committed, self.seeks, self.subscribed, self.closed = [], [], None, False

    def subscribe(self, topics):
        self.subscribed = topics

    def poll(self, _timeout):
        return self.queue.pop(0) if self.queue else None

    def commit(self, message, asynchronous):
        assert asynchronous is False
        self.committed.append(message.offset())

    def seek(self, tp):
        self.seeks.append((tp.topic, tp.partition, tp.offset))
        # a real consumer redelivers from the sought offset: put the message back
        self.queue.insert(0, self.last_failed)

    def close(self):
        self.closed = True


def make(messages, handler):
    fake = FakeConsumer(messages)
    return EventConsumer("t", handler, consumer=fake, backoff=0), fake


def ev(offset, **fields):
    return Msg(json.dumps({"id": offset} | fields).encode(), offset)


def test_commits_after_each_handled_event_in_order():
    seen = []
    c, fake = make([ev(1), ev(2)], seen.append)
    c.poll_once(), c.poll_once(), c.poll_once()          # third poll: nothing
    assert [e["id"] for e in seen] == [1, 2]
    assert fake.committed == [1, 2] and fake.seeks == []


def test_malformed_event_is_skipped_and_committed():
    seen = []
    c, fake = make([Msg(b"not json", 1), ev(2)], seen.append)
    c.poll_once(), c.poll_once()
    assert [e["id"] for e in seen] == [2]
    assert fake.committed == [1, 2]                      # moving on: it will never parse


def test_handler_value_or_key_error_counts_as_malformed():
    def handler(event):
        raise KeyError("author")

    c, fake = make([ev(1)], handler)
    c.poll_once()
    assert fake.committed == [1] and fake.seeks == []


def test_handler_failure_seeks_back_and_retries_without_committing():
    calls = []

    def handler(event):
        calls.append(event["id"])
        if len(calls) == 1:
            raise RuntimeError("database down")

    c, fake = make([ev(7)], handler)
    fake.last_failed = fake.queue[0]
    c.poll_once()                                        # fails: seek back, no commit
    assert fake.committed == [] and fake.seeks == [("t", 0, 7)]
    c.poll_once()                                        # redelivered: succeeds, committed once
    assert calls == [7, 7] and fake.committed == [7]


def test_broker_errors_are_not_handled_or_committed():
    seen = []
    c, fake = make([Msg(None, 0, error=Err(KafkaError._PARTITION_EOF)), Msg(None, 0, error=Err(-1))], seen.append)
    c.poll_once(), c.poll_once()
    assert seen == [] and fake.committed == []


def test_start_subscribes_and_stop_closes():
    c, fake = make([], lambda e: None)
    c.start()
    c.stop()
    assert fake.subscribed == ["t"] and fake.closed


def test_real_consumer_never_auto_commits():
    c = EventConsumer("t", lambda e: None, bootstrap="localhost:9", group_id="g")
    assert c.config["enable.auto.commit"] is False and c.config["group.id"] == "g"
    with pytest.raises(ValueError):
        EventConsumer("t", lambda e: None)                # neither a consumer nor bootstrap + group
