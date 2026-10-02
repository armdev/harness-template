# harness-template

An **agent harness as a product**: guides that steer a coding agent before it acts, and sensors that tell it
what went wrong after — versioned, containerised and measured. It ships with **haytarar**, a small but real
reference system (Python microservices, signed service-to-service calls, PostgreSQL with a role per service,
Flyway, Kafka, Prometheus) so every guide and sensor runs against working code from the first `make up`.

> Guides steer before the act; sensors correct after it.

Requirements: Docker Engine 26+ with Compose v2.24+ (volume `subpath`), GNU make. The host plane
(`harness-integration`, `harness-pipeline`) also needs `python3` with PyYAML.

## Quick start

```bash
cp .env.example .env               # optional: every variable has a default
make up                            # build + start the stack, wait until healthy (API on :8080)
make harness-fast                  # static sensors + advisory review → .harness/report.md
make harness-integration           # unit + contract suite against the running stack
make harness-selftest              # prove every sensor still fires on seeded defects

curl -s -XPOST localhost:8080/api/posts -H 'content-type: application/json' \
     -d '{"title":"Hello","body":"First post","author":"me"}'
curl -s 'localhost:8080/api/search?q=hello'
```

Optional: `make llm` (local Ollama for the review agent), `make up-observability` (Prometheus on :9090),
`make eval` (search quality vs. baseline), `make help` (all targets).

## Using it with a coding agent

| Agent | Wiring in this repo |
|---|---|
| Any | `AGENTS.md` (entry point), `harness/skills/*/SKILL.md`, `harness/prompts/agent/task.md` (task kickoff template) |
| Claude Code | `CLAUDE.md` imports `AGENTS.md`; skills under `.claude/skills/`; a Stop hook (`harness/hooks/agent-stop.sh`) sends the agent back while the static sensors are RED |
| git | `git config core.hooksPath .githooks` runs the blocking static sensors before each commit |
| CI | `.github/workflows/harness.yml`: selftest, fast loop, stack + integration, pipeline |

## Layout

```
AGENTS.md  CLAUDE.md          entry points for agents
harness.yaml                  manifest: every guide and sensor, its plane, stage, blocking flag, pairing
harness.mk  compose.harness.yml   make targets; the two sensor containers (static: no network, live: LLM/stack)
harness/
  harness.py                  runner: run · selftest · coverage · stats · list
  Dockerfile                  runner image with pinned tool versions (the distributable part)
  sensors/                    topology_check.py · migrations_check.py · review.py · fixtures/ (seeded defects)
  rules/semgrep/              organisation rules; messages are written for the agent
  review/RUBRIC.md            one rubric for the coding agent (forward) and the review agent (back)
  skills/                     new-service · new-endpoint · db-migration · new-topic · harness-report · harness-steer
  prompts/                    reviewer and judge system prompts; agent task / fix-red / done-check templates
  hooks/agent-stop.sh         agent Stop hook
  tests/                      tests of the harness itself (make harness-test)
docker-compose.yml            the reference system's architecture (checked by the topology sensor)
services/  libs/common/       gateway · content · search; signed calls, logging, metrics
db/migrations/                Flyway
contract/  eval/  tools/      API specification · search-quality eval · test tooling image
infra/prometheus/             scrape config and alert rules
```

Read `harness/HARNESS.md` for the design: planes, stages, versioning and the steering loop.
