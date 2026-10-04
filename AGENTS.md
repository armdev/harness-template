# AGENTS.md — air-harness

You are working in a Python microservice system run by one `docker-compose.yml`. The compose file is the
architecture: services, their identities, who may call whom, and which database role each one uses.

```
browser ──HTTP──> web (rag-web portal) ──signed──┐
client ──HTTP──> gateway <───────────────────────┘ ──signed──> content ──Kafka: content.post.created──┬──> search
                    ├─────signed──────────────────────────────────────────────┼──> search
                    ├─────signed──────────────────────────────────────────────┼──> notify
                    ├─────signed──────────────────────────────────────────────└──> graph
                    └─signed─> chat ──signed──> search, graph, content (retrieval) ──> LLM (OpenAI-compatible)
        content, search, notify ─ postgres: one role and schema each (content_svc/content, search_svc/search,
                                  notify_svc/notify)
        graph ─ neo4j: (:Author)-[:WROTE]->(:Post)-[:TAGGED]->(:Tag); its schema in db/graph (graph-init)
```

## Structure you must preserve
- One service per directory under `services/`; shared code only in `libs/common`.
- A language model is an external endpoint, called only through `common.llm` (never a raw HTTP client in a service).
- Service-to-service calls are signed (Ed25519, `common.service_auth`). A callee accepts only the callers
  listed in its `TRUSTED_CALLERS`. New call = `SignedClient` + callee's `TRUSTED_CALLERS` + key in `service-keys`.
- Each service has its own database role (`<name>_svc`) and schema. Schema changes go only into `db/migrations`
  (Flyway); a committed migration is never edited. The graph store's constraints go only into `db/graph/*.cypher`.
- Kafka topics are created by `kafka-init`; auto-create is off. New topic = new entry there.
- The `contract/` suite is the specification of the public API. Change it only when the task asks for new behaviour.
- Persistent data lives under `DATA_DIR`, never inside the repository.
- Configuration is an env var with a default in compose: `${NAME:-default}` plus a one-line comment, and an
  entry in `.env.example`.

## Skills (follow the one that matches your task)
| Task | Skill |
|---|---|
| new deployable, or a new caller → callee edge | `harness/skills/new-service/SKILL.md` |
| new or changed endpoint | `harness/skills/new-endpoint/SKILL.md` |
| schema change, new role | `harness/skills/db-migration/SKILL.md` |
| new event / producer / consumer | `harness/skills/new-topic/SKILL.md` |
| a sensor failed, or before you say "done" | `harness/skills/harness-report/SKILL.md` |
| change the harness itself (only when asked) | `harness/skills/harness-steer/SKILL.md` |

## How you get feedback
1. After each change: `make harness-fast` (static sensors, no network, < 1 min; plus an advisory review).
2. Read `.harness/report.md`. Fix **blocking failures** first; each one says how to fix and how to re-run it alone.
3. **Blind sensors** in the report are harness problems, not your code: report them, do not work around them.
4. Before you declare a task done, with the stack up (`make up`): `make harness-integration` (unit + contract).

## Commands
`./run.sh` (start + URLs) · `./run.sh --urls` · `./help.sh` · `make up` · `make down` · `make ps` · `make logs s=<service>` · `make test` · `make contract` · `make eval` ·
`make harness-fast` · `make harness-one s=<sensor>` · `make help` for the rest.

## What reviewers check
`harness/review/RUBRIC.md` — read it before writing; the review agent applies the same rubric to your diff.

## Never
Edit `harness.yaml`, `harness/sensors/`, fixtures, `RUBRIC.md` or existing contract tests to make a sensor pass;
add `sleep`, broad `except`, `noqa` or `nosemgrep` to silence one; write data into the repository.
