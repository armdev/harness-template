---
name: new-topic
description: Add a Kafka topic, producer or consumer to haytarar. Use whenever a task publishes or consumes an event between services.
---

# Add an event

Topics are created by the `kafka-init` one-shot and nowhere else: the broker runs with auto-create off, so a
producer to a topic that is not declared fails at runtime.

1. **Declare the topic** in `services.kafka-init.environment.TOPICS` as `<owner>.<entity>.<event>:<partitions>`,
   e.g. `content.post.created:3`. The owner is the service that produces it. Past tense: it is a fact.
2. **Wait for it**: every producer and consumer has `kafka-init: { condition: service_completed_successfully }`
   in its `depends_on` (topology T5), and `KAFKA_BOOTSTRAP: kafka:9092` in its environment.
3. **Producer** (see `services/content/app.py`): `acks=all`, `enable.idempotence=True`; key = the entity id so
   all events of one entity are ordered; value = the full entity as JSON (consumers should not have to call back).
   Produce after the database commit and check the `flush()` result.
4. **Consumer** (see `services/search/indexer.py`): its own `group.id` (= service name),
   `enable.auto.commit=False`, commit only after the side effect succeeded, upsert so redelivery is harmless,
   seek back and back off when the database is down (rubric R8).
5. **Schema changes** to an existing event: only add fields. Removing or renaming a field needs a new topic
   (`...created.v2`) and a migration period with both.
6. **Behaviour**: a contract test that observes the effect through the public API with `eventually(...)`.
7. **Verify**: `make harness-fast`, `make up` (`kafka-init` exits 0), `make contract`.

Inspect: `docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --describe`.
