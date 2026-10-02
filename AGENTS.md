# AGENTS.md — haytarar

You are working in a Python microservice system run by one `docker-compose.yml`. The compose file is the
architecture: services, their identities, who may call whom, and which database role each one uses.

## Structure you must preserve
- One service per directory under `services/`; shared code only in `libs/common`.
- Service-to-service calls are signed (Ed25519, `common.service_auth`). A callee accepts only the callers
  listed in its `TRUSTED_CALLERS`. New call = signed client + callee's `TRUSTED_CALLERS` + key in `service-keys`.
- Each service has its own database role (`<name>_svc`). Schema changes go only into `db/migrations` (Flyway).
- Kafka topics are created by `kafka-init`; auto-create is off. New topic = new entry there.
- `content` and `search` have two implementations (`IMPL=python|java`) behind one API. The `contract/`
  suite is the specification for both.
- Persistent data lives under `DATA_DIR`, never inside the repository.
- Configuration is an env var with a default in compose: `${NAME:-default}` plus a one-line comment.

## Adding a service
Follow `harness/skills/new-service/SKILL.md`. The topology sensor checks the result.

## How you get feedback
1. After each change: `make harness-fast` (static sensors, no network, < 1 min; plus an advisory review).
2. Read `.harness/report.md`. Fix **blocking failures** first; each one says how to fix and how to re-run it alone.
3. **Blind sensors** in the report are harness problems, not your code: report them, do not work around them.
4. Before you declare a task done, with the stack up: `make harness-integration` (contract suite).

## What reviewers check
`harness/review/RUBRIC.md` — read it before writing; the review agent applies the same rubric to your diff.
