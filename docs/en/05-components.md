# 5. Components

## 5.1 Repository map

```
run.sh  help.sh               product entry points
AGENTS.md  CLAUDE.md          agent entry points
harness.yaml                  manifest (guides + sensors)
harness.mk  compose.harness.yml   harness targets; sensor containers
Makefile                      product targets (+ include harness.mk)
harness/                      the harness
docker-compose.yml  .env.example  reference system architecture and configuration
services/  libs/common/       application code
db/migrations/                Flyway
contract/  eval/  tools/      specification, search eval, test tooling image
infra/prometheus/             scrape config, alert rules
.claude/  .githooks/  .github/workflows/   agent, git and CI wiring
docs/                         this documentation
```

## 5.2 Harness components

| Component | Path | Responsibility | Inputs → outputs |
|---|---|---|---|
| Manifest | `harness.yaml` | declares every guide and sensor as data | — → read by the runner |
| Runner | `harness/harness.py` | verbs `run`, `selftest`, `coverage`, `stats`, `list`; executes sensors, classifies results, writes report and ledger | manifest, env → `.harness/` |
| Runner image | `harness/Dockerfile` | pinned tools: ruff, semgrep, vulture, pip-audit, pytest, PyYAML, git | — → `air-harness-runner:<ver>` |
| Sensor containers | `compose.harness.yml` | `harness` (static plane) and `harness-live` (live plane) from one image | repo (ro) → `/out` |
| Make targets | `harness.mk` | stage entry points, one-sensor re-run, selftest, coverage, stats, harness tests | — |
| Topology sensor | `harness/sensors/topology_check.py` | checks `docker-compose.yml` against itself: T1–T10 | compose file, alerts file, env example → findings |
| Migrations sensor | `harness/sensors/migrations_check.py` | Flyway history rules M1–M5 | `db/migrations`, git → findings |
| Review sensor | `harness/sensors/review.py` | LLM applies the rubric to the diff (`REVIEW_SCOPE`; `REVIEW_DIFF_FILE` for seeded diffs) | diff, rubric, prompt → findings (advisory) |
| Dependency audit | `harness/sensors/deps_audit.py` | pip-audit on every requirements file; exit 126 (BLIND) when it cannot audit | requirements files, network → findings |
| Mutation helper | `harness/sensors/mutate.py` | applies one mutant to a copy of `libs/common` or `services/gateway` and runs the suite that must catch it | `mutant.yml` → exit code of the suite |
| Semgrep rules | `harness/rules/semgrep/python.yml` | organisation rules whose messages say what to write instead | code → findings |
| Vulture whitelist | `harness/rules/vulture_whitelist.py` | framework-used names that look dead | — |
| Seeded defects | `harness/sensors/fixtures/` | prove each sensor fires (`# expect: <rule>`) and stays quiet (`# expect: clean`): files, diffs, eval baselines, mutants — every sensor has them | — → `.harness/selftest.json` (read by `stats`) |
| Rubric | `harness/review/RUBRIC.md` | R1–R9: one rubric for the agent (forward) and the reviewer (back) | — |
| Skills | `harness/skills/*/SKILL.md` | procedures: new-service, new-endpoint, db-migration, new-topic, harness-report, harness-steer | — |
| Prompts | `harness/prompts/` | reviewer and judge system prompts; agent templates; next-step prompts 01–08 | — |
| Stop hook | `harness/hooks/agent-stop.sh` | blocks an agent from finishing while static sensors are RED | hook JSON on stdin → exit 0/2 |
| Harness tests | `harness/tests/` | tests of the runner and sensors | — |
| Changelog | `harness/CHANGELOG.md` | versions and expected first-run impact of new rules | — |
| Console | `harness/console/server.py`, `static/` | web UI on 127.0.0.1:8090: OpenAPI-driven API forms, allowlisted make targets with live output, sensors, report, agent runs (`AGENT_CMD`), ledger timeline, guides | `.harness/`, manifest, gateway → browser |
| Installer | `harness/install.py` | installs the harness into another project with a manifest that fits it; `--upgrade` replaces only upstream-owned machinery | project dir → harness files, `harness.yaml` |
| Install templates | `harness/templates/` | `AGENTS.md`, `CLAUDE.md`, `ruff.toml` written into a project that has none | — |

### Sensors

| id | Kind | Plane | Stages | Blocking | Command |
|---|---|---|---|---|---|
| topology | computational | static | pre-commit, pipeline | yes | `topology_check.py docker-compose.yml` |
| migrations | computational | static | pre-commit, pipeline | yes | `migrations_check.py db/migrations` |
| ruff | computational | static | pre-commit, pipeline | yes | `ruff check services libs contract eval` |
| semgrep-local | computational | static | pre-commit, pipeline | yes | `semgrep scan --config harness/rules/semgrep` |
| review-agent | inferential | live | pre-commit | no | `review.py` |
| unit | computational | host | integration, pipeline | yes | `make test` |
| contract | computational | host | integration, pipeline | yes | `make contract` |
| eval | computational | host | pipeline | yes | `make eval` |
| prom-rules | computational | host | pipeline | yes | `promtool check rules` |
| dead-code | computational | static | continuous | no | `vulture … --min-confidence 80` |
| deps-audit | computational | live | continuous | no | `harness/sensors/deps_audit.py` (pip-audit on each requirements file) |

Selftest helpers: `harness/sensors/mutate.py` applies one mutant (`harness/sensors/fixtures/{unit,contract}/<name>/mutant.yml`) to a copy of the code: `target: unit` mounts a mutated `libs/common` into the unit tests, `target: gateway` runs a second, mutated gateway next to the stack and points the contract suite at it; a mutant that no longer applies exits 126 (BLIND).

### Guides

`AGENTS.md`, six skills, `RUBRIC.md`, semgrep rule messages, `harness/prompts/`, `contract/README.md`,
`eval/README.md` — 12 guides in the manifest, each paired with at least one sensor except the two process
skills (`harness-report`, `harness-steer`), which `harness-coverage` reports honestly as feedforward-only.

## 5.3 Product surface

| Component | Responsibility |
|---|---|
| `run.sh` | preflight (docker, compose, make, free ports) → `make up[-observability]` → smoke test (create → read → search) → optional harness stages → URLs → next steps. Modes `--check`, `--full`, `--llm`, `--urls`, `--down`, `--no-observability`. |
| `help.sh` | terminal guide: `run`, `commands`, `urls`, `harness`, `agent`, `prompts`, `config`, `troubleshoot`; `prompt <n>` prints a prompt; fills `{{task}}` and `{{report_md}}`. |
| `Makefile` | `up`, `up-observability`, `down`, `ps`, `logs`, `build`, `test`, `contract`, `eval`, `llm`, `clean`, `purge`, `help`. |

## 5.4 Reference system components

| Component | Path | Responsibility |
|---|---|---|
| Shared library | `libs/common/common/` | `service_auth` (Ed25519 signing client, verifier, FastAPI dependency), `telemetry` (`create_app`: JSON logs, request id, `/healthz`, `/metrics`, HTTP metrics), `keygen` (identity generation), `events` (`EventConsumer`: Kafka consumer loop with commit-after-handler, skip malformed, retry on failure), `llm` (`ChatModel`: streamed completions from an OpenAI-compatible endpoint, `ThinkFilter`), `relay` (pass a streamed answer through, signed) |
| gateway | `services/gateway/app.py` | public routes `/api/posts` (create, list by author), `/api/posts/{id}`, `/api/search`, `/api/notifications`; signed forwarding; `/` → `/docs` |
| content | `services/content/app.py` | `POST /posts`, `GET /posts/{id}`, `GET /posts?author=`; writes `content.posts`; produces `content.post.created` |
| search | `services/search/app.py`, `indexer.py` | `GET /search` (author and tag filters); `EventConsumer` with a handler upserting `search.documents`; Postgres full-text ranking |
| notify | `services/notify/app.py`, `consumer.py` | `GET /outbox`; `EventConsumer` with a handler recording one `notify.outbox` row per post (idempotent) |
| planner | `services/planner/app.py`, `planning.py` | employees, tasks, meetings (Postgres, schema `planner`); task priority with reasons, week schedule around meetings, model re-plan checked by the rules, work graph — see [Planner](08-planner.md) |
| chat | `services/chat/app.py`, `rag.py` | `POST /chat`: fixed RAG pipeline (search → graph → content → model) answering with `[#id]` citations, streamed as server-sent events; lists the sources when no model is reachable |
| web (rag-web) | `services/web/app.py`, `static/` | the portal: browser client (analyze, search, graph explorer, chat, write, post/tag/author pages) and a signed, streaming `/api/*` proxy to the gateway |
| graph | `services/graph/app.py`, `graph.py` | `GET /related/{post_id}`, `GET /tags/{tag}`, `GET /tags/{tag}/posts`, `GET /overview`; `EventConsumer` with a handler MERGEing `(:Author)-[:WROTE]->(:Post)-[:TAGGED]->(:Tag)` in Neo4j (idempotent) |
| Graph schema | `db/graph/*.cypher`, `graph-init` | uniqueness constraints on `Post.id`, `Author.name`, `Tag.name`; applied with `cypher-shell` before `graph` starts |
| Migrations | `db/migrations/V1..V7` | roles `content_svc`, `search_svc`, `notify_svc`; schemas `content`, `search`, `notify`; tables, indexes, tags, grants |
| One-shots | `docker-compose.yml` | `storage-init` (DATA_DIR layout), `service-keys` (identities), `migrate` (Flyway), `kafka-init` (topics) |
| Infrastructure | `docker-compose.yml` | `postgres`, `kafka` (KRaft), `prometheus` (profile), `ollama` (profile) |
| Contract suite | `contract/` | specification of the public API and of the auth boundary (32 tests) |
| Unit tests | `libs/common/tests/` | signing, verification, spoofing, tampering, skew, keygen idempotence |
| Eval | `eval/` | corpus + queries, `run_eval.py`, `baseline.json` |
| Tools image | `tools/Dockerfile`, `tools/seed.py` | pytest, httpx, PyYAML, `libs/common` for contract, unit, eval and seed containers; `seed.py` loads a sample dataset through the API (idempotent) |
| Observability | `infra/prometheus/` | scrape jobs and up / error-rate / latency alerts per service |

## 5.5 Wiring

| Component | Path | Responsibility |
|---|---|---|
| Claude Code | `CLAUDE.md`, `.claude/settings.json`, `.claude/skills/*` (symlinks) | imports AGENTS.md, exposes skills, registers the Stop hook, allows harness commands |
| git hook | `.githooks/pre-commit` | `make harness-static` before every commit |
| CI | `.github/workflows/harness.yml` | build runner → harness tests, coverage, selftest → static sensors → `./run.sh --full`; report in the job summary and as an artifact; nightly continuous stage |

Next: [Low-level design](06-low-level-design.md)
