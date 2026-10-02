# Harness template `py-services-pg-kafka` v0.1.0

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
| Runner | `harness/harness.py` | `run`, `selftest`, `coverage`, `stats` — PyYAML only |
| Runner image | `harness/Dockerfile` | pinned tool versions; the distributable, versioned part |
| Sensor planes | `compose.harness.yml` | `harness` (no network, read-only) and `harness-live` (LLM, stack) |
| Make targets | `harness.mk` | `harness-fast`, `-integration`, `-pipeline`, `-continuous`, `-selftest`, `-coverage`, `-stats` |
| Guides | `AGENTS.md`, `harness/skills/new-service/SKILL.md`, `harness/review/RUBRIC.md`, `harness/rules/semgrep/` | feedforward |
| Custom sensors | `harness/sensors/topology_check.py`, `harness/sensors/review.py` | feedback written for the agent |
| Seeded defects | `harness/sensors/fixtures/` | proof that each sensor can still fire |

## Instantiate

```bash
cp -r harness harness.yaml compose.harness.yml harness.mk AGENTS.md <project>/
echo 'include harness.mk' >> <project>/Makefile
echo '.harness/' >> <project>/.gitignore
make harness-coverage      # gaps before you start
make harness-selftest      # sensors fire on seeded defects
make harness-fast          # first real run; read .harness/report.md
```

Wire the fast loop where the agent and the human both hit it:

```bash
# git: .githooks/pre-commit  (git config core.hooksPath .githooks)
make harness-fast
```

For a coding agent with post-edit hooks (Claude Code shown; check your agent's hook format), run the fast
loop after edits so the report is fresh when the agent reads it:

```json
{ "hooks": { "PostToolUse": [ { "matcher": "Edit|Write",
  "hooks": [ { "type": "command", "command": "make -s harness-fast >/dev/null 2>&1 || true" } ] } ] } }
```

## Lifecycle (keep quality left)

| Stage | Where | Sensors | Budget |
|---|---|---|---|
| pre-commit | `harness` + `harness-live` | topology, ruff, semgrep (blocking); review agent (advisory) | < 1 min |
| integration | host, stack up | contract suite | minutes |
| pipeline | CI | all of the above + Java parity, eval (search/RAG + judge), Prometheus rules | tens of minutes |
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
