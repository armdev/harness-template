# Harness template `py-services-pg-kafka` v0.3.2

A harness template for one topology: Python microservices in one compose file, signed service-to-service
calls, PostgreSQL with a role per service, Flyway, Kafka, an OpenAI-compatible local LLM.
It gives a coding agent **guides** (what to do, before it acts) and **sensors** (what went wrong, after it acts),
and it is packaged so that it can be versioned, instantiated and measured like any other product.

> Guides steer before the act; sensors correct after it.
> A service template tells the agent where to stand; a harness template tells it when it fell.

## What is in the box

| Piece | File | Role |
|---|---|---|
| Manifest | `harness.yaml` | every guide and sensor as data: kind, category, plane, stage, blocking, pairing |
| Runner | `harness/harness.py` | `run`, `selftest`, `coverage`, `stats`, `list` — PyYAML only |
| Runner image | `harness/Dockerfile` | pinned tool versions; the distributable, versioned part |
| Sensor planes | `compose.harness.yml` | `harness` (no network, read-only) and `harness-live` (LLM, stack) |
| Make targets | `harness.mk` | `harness-fast`, `-static`, `-integration`, `-pipeline`, `-continuous`, `-one`, `-selftest`, `-coverage`, `-stats`, `-test` |
| Guides | `AGENTS.md`, `harness/skills/*/SKILL.md`, `harness/review/RUBRIC.md`, `harness/rules/semgrep/`, `harness/prompts/` | feedforward |
| Custom sensors | `harness/sensors/topology_check.py`, `migrations_check.py`, `review.py` | feedback written for the agent |
| Seeded defects | `harness/sensors/fixtures/` | proof that each sensor can still fire — and stays quiet on clean input |
| Agent wiring | `CLAUDE.md`, `.claude/`, `harness/hooks/agent-stop.sh`, `.githooks/pre-commit` | puts the loop where the agent and the human both hit it |
| Harness tests | `harness/tests/` | the harness is code too: `make harness-test` |

### Sensors

| id | plane | stages | blocking | what it proves |
|---|---|---|---|---|
| `topology` | static | pre-commit, pipeline | yes | compose is internally consistent: T1 trusted callers, T2 keys, T3 default drift, T4 migrate-first, T5 topics-first, T6 pinned images, T7 alerts, T8 documented env, T9 no data in the repo, T10 callees can verify signatures |
| `migrations` | static | pre-commit, pipeline | yes | Flyway history is append-only, well named, and every table is granted |
| `ruff` | static | pre-commit, pipeline | yes | lint (incl. bandit-style `S`, blind excepts) |
| `semgrep-local` | static | pre-commit, pipeline | yes | organisation rules: parameterised SQL, TLS on, no DDL in code, logging, signed calls only, Kafka consumers commit after the write |
| `review-agent` | live | pre-commit | no | rubric applied to the diff by an LLM (opt-in: SKIPPED without `LLM_BASE_URL`) |
| `unit` | host | integration, pipeline | yes | `libs/` unit tests |
| `contract` | host | integration, pipeline | yes | the public API behaves as specified (stack up) |
| `eval` | host | pipeline | yes | search quality: recall@5 / MRR@10 vs. `eval/baseline.json` (an optional LLM judge@1 is advisory) |
| `prom-rules` | host | pipeline | yes | alert rules parse (promtool) |
| `dead-code` | static | continuous | no | vulture |
| `deps-audit` | live | continuous | no | known-vulnerable pinned dependencies (BLIND, not FAIL, when pip-audit cannot run) |

### Sensor contract

A sensor is any command. Exit 0 = pass, 125 = skipped (not configured; advisory sensors only), 126/127 = blind
(the runner reports it as a harness problem, never as a code failure), anything else = fail. Findings are one per line starting with `ERROR` or `WARN`, followed by
indented `what:` and `fix:` lines; `WARN` lines of a passing sensor still reach the report. Seeded defects
start with `# expect: <text the sensor must print>` or `# expect: clean`.

## Instantiate

In this repository everything is already wired (`make up`, `make harness-fast`). For another project of the
same topology:

```bash
cp -r harness harness.yaml compose.harness.yml harness.mk AGENTS.md CLAUDE.md .claude .githooks pyproject.toml <project>/
echo 'include harness.mk' >> <project>/Makefile
echo '.harness/' >> <project>/.gitignore
# in <project>/docker-compose.yml: x-harness: { alerts: <alert rules file>, env_example: .env.example }
make harness-coverage      # gaps before you start
make harness-selftest      # sensors fire on seeded defects (make harness-selftest-live: network sensors)
make harness-fast          # first real run; read .harness/report.md
```

The fast loop sits where the agent and the human both hit it:

- **git**: `git config core.hooksPath .githooks` — `make harness-static` before each commit.
- **Claude Code**: `.claude/settings.json` registers `harness/hooks/agent-stop.sh` as a `Stop` hook. When the agent
  tries to finish with uncommitted changes and the static sensors are RED, the hook exits 2 and the agent is sent
  back with the head of the report. It lets the agent stop on the second attempt (`stop_hook_active`), so a
  broken harness can never trap it. Other agents: run the same script from their end-of-turn hook.
- **CI**: `.github/workflows/harness.yml`.

## Lifecycle (keep quality left)

| Stage | Where | Sensors | Budget |
|---|---|---|---|
| pre-commit | `harness` + `harness-live` | topology, migrations, ruff, semgrep (blocking); review agent (advisory) | < 1 min |
| integration | host, stack up | unit, contract suite | minutes |
| pipeline | CI | all of the above + unit, contract, eval (search + judge), Prometheus rules | tens of minutes |
| continuous | nightly | dead code, dependency vulnerabilities | — |

## Versioning: why this is a product and not a copy

Templates drift the moment they are copied. The split that keeps upgrades possible:

- **Upstream-owned, pinned**: the runner image (`HARNESS_IMAGE`), the generic sensors, the semgrep rule pack,
  the seeded defects. Upgraded by bumping a tag; release notes list new rules and their expected first-run impact.
- **Project-owned, versioned with the code**: `harness.yaml`, `AGENTS.md`, project rules and fixtures.
  `template.version` in the manifest records which upstream it was last reconciled with.
- **Contribution path**: a project rule that fires usefully for a month (`make harness-stats`) is a candidate
  for the upstream pack.

## Steering loop

1. `harness-stats`: a sensor that fires often → strengthen its paired guide (the agent keeps making that mistake).
2. A sensor that never fires in 20+ runs → `harness-selftest`. If it still fires on seeded defects, the code is
   genuinely clean there — consider moving it to a later stage; if not, it is blind.
3. `harness-coverage`: a guide with no sensor is a rule nobody checks; a sensor with no guide is a lesson
   nobody teaches.
4. Inferential sensors stay advisory until their precision has been measured on real diffs.

## Extending to a second implementation

The original design kept two implementations of `content`/`search` (`IMPL=python|java`) behind one API. This
version ships only Python. To add another: build it from `services/<name>/<impl>/`, select it with
`build.dockerfile: services/<name>/${IMPL:-python}/Dockerfile`, and add a pipeline sensor
`contract-<impl>-parity` with `run: IMPL=<impl> make contract` — the contract suite is already the shared
specification.
