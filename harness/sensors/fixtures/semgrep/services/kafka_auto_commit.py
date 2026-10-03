# expect: kafka-consumer-auto-commit
from confluent_kafka import Consumer


def default_consumer(bootstrap):
    # auto-commit is librdkafka's default: offsets are committed whether or not the event was handled
    return Consumer({"bootstrap.servers": bootstrap, "group.id": "audit"})


def explicit_auto_commit(bootstrap):
    return Consumer({"bootstrap.servers": bootstrap, "group.id": "audit", "enable.auto.commit": True})
