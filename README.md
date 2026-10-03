# air-harness

**An agent harness as a product.** Guides steer a coding agent *before* it acts; sensors tell it what went wrong
*after* — versioned, containerised, measured. air-harness ships with a small but real reference system (Python
microservices, signed service-to-service calls, PostgreSQL with a role per service, Flyway, Kafka, Prometheus)
so every guide and sensor works on running code from the first command.

> Guides steer before the act; sensors correct after it.

![air-harness demo: run, API, observability, a RED report, the Stop hook, GREEN, prompts](docs/assets/demo-en.gif)

*A 46-second walkthrough of a real run — more in the [demo page](docs/en/07-demo.md) ([по-русски](docs/ru/07-demo.md)).*

**Documentation:** [docs/](docs/README.md) — what a harness is, how to use it, use cases, architecture,
components, low-level design and a demo, in [English](docs/en/01-what-is-a-harness.md) and
[Russian](docs/ru/01-what-is-a-harness.md).

## 1. Run it

```bash
./run.sh            # build + start everything, smoke-test it, print every URL and the next steps
./help.sh           # the guide, in your terminal
```

`./run.sh` checks your machine, starts the stack, waits until every service is healthy, creates a post, reads
it back, finds it through search, and prints where everything is:

```
Accessible URLs
  Public API                 http://localhost:8080  (opens the docs)
  API docs (Swagger UI)      http://localhost:8080/docs
  API docs (ReDoc)           http://localhost:8080/redoc
  OpenAPI schema             http://localhost:8080/openapi.json
  Gateway health / metrics   http://localhost:8080/healthz · /metrics
  Prometheus                 http://localhost:9090 · /targets · /alerts
  Local LLM                  http://localhost:11434/v1   (with --llm)
```

| Command | What it does |
|---|---|
| `./run.sh` | start the stack (+ Prometheus), smoke test, URLs, next steps |
| `./run.sh --check` | … then prove the harness: selftest, fast loop, unit + contract suite |
| `./run.sh --full` | … `--check` plus the pipeline stage (search eval, alert rules) — what CI runs |
| `./run.sh --llm` | also start a local LLM (Ollama) for the review agent |
| `./run.sh --urls` | status and URLs of the running stack |
| `./run.sh --down` | stop (data is kept in `DATA_DIR`; `make purge` deletes it) |

Requirements: Docker Engine 26+ with Compose v2.24+, GNU make, bash, curl. The host-plane stages
(`--check`, `--full`) also need `python3` with PyYAML (`pip install pyyaml`). Configuration: every setting has
a default; `cp .env.example .env` to change one (`./help.sh config`).

## 2. Learn the loop

Every change — by you or by an agent — goes through the same loop:

```
edit → make harness-fast → read .harness/report.md → fix blocking failures first → repeat
before "done":  make up && make harness-integration     (unit + contract suite)
```

`.harness/report.md` starts with **GREEN** or **RED**. Each blocking failure says *how to fix*, *which guide
teaches the rule*, and *how to re-run only that sensor*. **BLIND** sensors are harness problems (e.g. no LLM for
the review agent): report them, never work around them. `./help.sh harness` explains the stages and sensors.

## 3. Hand it to a coding agent — next-step prompts

air-harness ships ready-to-use prompts for the steps you will take, in order. `./help.sh prompts` lists them;
`./help.sh prompt <n>` prints one, ready to paste into any agent:

| # | Prompt | Use it when |
|---|---|---|
| 01 | Get to know the repository | first session; nothing is changed |
| 02 | First feature: list posts by author | you want to watch the full loop on a small change (contract first) |
| 03 | Schema change: tags on posts | you want to see the migrations sensor and database rules |
| 04 | New service: notify | you want the topology sensor to teach the architecture |
| 05 | The harness is RED: fix only that | a report, the Stop hook or CI is RED |
| 06 | Review a change | before committing or opening a PR |
| 07 | Ship | run what CI runs and write the PR |
| 08 | Improve the harness | maintainers: tune sensors and guides from the data |

```bash
claude "$(./help.sh prompt 01)"                       # Claude Code, interactive
./help.sh prompt 02 | claude -p                       # Claude Code, headless
./help.sh prompt task "Add rate limiting to search"   # generic task prompt with your task filled in
./help.sh prompt fix-red                              # the RED report, wrapped in a fix-only prompt
```

What the agent gets in this repo:

| Agent | Wiring |
|---|---|
| Any | `AGENTS.md` (entry point), skills in `harness/skills/*/SKILL.md`, prompts in `harness/prompts/` |
| Claude Code | `CLAUDE.md` imports `AGENTS.md`; skills under `.claude/skills/`; a Stop hook (`harness/hooks/agent-stop.sh`) sends the agent back while the static sensors are RED |
| git | `git config core.hooksPath .githooks` runs the blocking static sensors before each commit |
| CI | `.github/workflows/harness.yml` runs `./run.sh --full` on every PR, the continuous stage nightly |

## 4. What is in the box

```
run.sh  help.sh               run the product · the guide in your terminal
AGENTS.md  CLAUDE.md          entry points for agents
harness.yaml                  manifest: every guide and sensor, its plane, stage, blocking flag, pairing
harness.mk  compose.harness.yml   harness make targets; the sensor containers (static: no network, live: LLM/stack)
harness/
  harness.py                  runner: run · selftest · coverage · stats · list
  Dockerfile                  runner image with pinned tool versions (the distributable part)
  sensors/                    topology_check.py · migrations_check.py · review.py · fixtures/ (seeded defects)
  rules/semgrep/              organisation rules; messages are written for the agent
  review/RUBRIC.md            one rubric for the coding agent (forward) and the review agent (back)
  skills/                     new-service · new-endpoint · db-migration · new-topic · harness-report · harness-steer
  prompts/                    next-steps/ (guided prompts) · agent/ (task, fix-red, done-check) · review · judge
  hooks/agent-stop.sh         agent Stop hook
  tests/                      tests of the harness itself (make harness-test)
docker-compose.yml            the reference system's architecture (checked by the topology sensor)
services/  libs/common/       gateway · content · search · notify; signed calls, logging, metrics
db/migrations/                Flyway
contract/  eval/  tools/      API specification · search-quality eval · test tooling image
infra/prometheus/             scrape config and alert rules
```

| Sensor | Stage | Blocking | Proves |
|---|---|---|---|
| `topology` | pre-commit | yes | compose is consistent: trusted callers, keys, defaults, startup order, pinned images, alerts, documented env, no data in the repo, callees can verify |
| `migrations` | pre-commit | yes | Flyway history is append-only, well named, every table granted |
| `ruff`, `semgrep-local` | pre-commit | yes | lint; organisation rules (parameterised SQL, TLS on, no DDL in code, signed calls only, Kafka consumers commit after the write) |
| `review-agent` | pre-commit | no | the rubric applied to the diff by an LLM |
| `unit`, `contract` | integration | yes | library tests; the public API behaves as specified |
| `eval`, `prom-rules` | pipeline | yes | search quality (recall@5, MRR@10) vs. baseline; alert rules parse |
| `dead-code`, `deps-audit` | continuous | no | drift |

## 5. Use it in your own project

air-harness is built to be copied and upgraded, not forked and forgotten. Projects pin the runner image and keep
their own manifest, guides and rules; see `harness/HARNESS.md` (design, versioning, steering loop) and
`harness/CHANGELOG.md`.

```bash
cp -r harness harness.yaml compose.harness.yml harness.mk AGENTS.md CLAUDE.md .claude .githooks pyproject.toml <project>/
echo 'include harness.mk' >> <project>/Makefile && echo '.harness/' >> <project>/.gitignore
make harness-coverage && make harness-selftest && make harness-fast
```
