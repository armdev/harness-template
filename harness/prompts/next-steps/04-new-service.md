# 04 · New service: notify

When: you want to see the topology sensor teach the architecture (identity, trust, alerts, env).
You should see: compose entry, key, TRUSTED_CALLERS, alerts, .env.example — each one prompted by a topology
finding if missed.

---
Task: add a `notify` service. It consumes `content.post.created` and, for every post, writes one row
`(post_id, author, created_at)` to its own table `notify.outbox` (a stand-in for sending an e-mail). It exposes
`GET /outbox?author=<author>` to the gateway, and the gateway publishes it as `GET /api/notifications?author=`.

Follow harness/skills/new-service/SKILL.md from step 1 to step 9 in order; use services/search as the model
for a Kafka consumer and services/content for a service with a database. Its database role is `notify_svc`.

Run `make harness-fast` after the compose change before writing any code: the topology sensor will tell you
what is still missing. Done when `make up && make harness-integration` is GREEN and the new endpoint has
contract tests. Summarise with harness/prompts/agent/done-check.md.
