# 1. What is a harness?

> **Guides steer before the act; sensors correct after it.**

A coding agent (Claude Code, Codex, Cursor, …) is fast, tireless and literal. Left alone it will happily add a
service that nobody may call, edit a database migration that already ran in production, or "fix" a failing
test by loosening the assertion. A **harness** is the structure around the agent that prevents this — not by
reviewing every line by hand, but by giving the agent two kinds of signals:

| | **Guides** (feedforward) | **Sensors** (feedback) |
|---|---|---|
| When | *before* the agent acts | *after* the agent acts |
| Purpose | tell it what good looks like here | tell it exactly what went wrong and how to fix it |
| Examples in air-harness | `AGENTS.md`, skills (`harness/skills/*/SKILL.md`), the review rubric, rule messages, prompts | topology check of `docker-compose.yml`, migration check, ruff, semgrep, contract tests, LLM review, search eval |
| Failure mode alone | rules nobody checks | the agent repeats the same mistake |

A guide without a sensor is a rule nobody verifies. A sensor without a guide is a lesson nobody teaches. The
harness pairs them and **measures** both.

## Computational vs. inferential

Every guide and sensor is one of two kinds:

- **Computational** — deterministic, cheap, exact: a parser, a linter, a test. Same input, same answer.
  These may **block** (fail the build).
- **Inferential** — an LLM judges: the review agent, the eval judge. Useful for what needs judgement, but
  noisy. They stay **advisory** until their precision on real diffs has been measured.

The rule of thumb that drives the design: *whenever a rule can be computational, make it computational*. Prose
in a guide is the last resort, not the first.

## Why a harness is a product, not a folder

Templates drift the moment they are copied. air-harness is built like a product:

- **Declared as data** — every guide and sensor is an entry in one manifest (`harness.yaml`): kind, category,
  where it runs (plane), when it runs (stage), whether it blocks, which guide it pairs with.
- **Versioned** — the runner image with pinned tool versions is the distributable part; projects pin it and
  upgrade by bumping a tag (`harness/CHANGELOG.md` lists the expected impact of new rules).
- **Self-testing** — every computational sensor has *seeded defects* (fixtures that must make it fire) and
  clean fixtures (that must keep it quiet). `make harness-selftest` proves a quiet sensor is not a blind one.
- **Measured** — every sensor run is appended to a ledger. `make harness-stats` shows which sensors fire often
  (the paired guide is weak), which never fire, and which are blind. That is the **steering loop**.

## What air-harness contains

1. **The harness** — manifest, runner, sensors, rules, rubric, skills, prompts, hooks and CI wiring.
2. **A reference system** that the harness regulates, so everything runs on real code from the first command:
   three Python services (gateway, content, search) with Ed25519-signed service-to-service calls, PostgreSQL
   with a role and schema per service, Flyway migrations, Kafka, Prometheus — all in one `docker-compose.yml`.
3. **The product surface** — `run.sh` (run everything, print every URL), `help.sh` (the guide in your
   terminal) and ready-to-paste next-step prompts for coding agents.

## Vocabulary

| Term | Meaning |
|---|---|
| **Guide** | Anything that steers the agent before it acts (document, skill, rule message, prompt). |
| **Sensor** | A command that checks the result after the agent acts. Exit 0 = pass. |
| **Plane** | Where a sensor runs: `static` (container, no network), `live` (container on the project network: LLM, stack), `host` (your machine / CI through make and docker compose). |
| **Stage** | When a sensor runs: `pre-commit` < `integration` < `pipeline` < `continuous`. Keep quality left. |
| **Blocking** | A failing blocking sensor turns the report RED. Advisory sensors only inform. |
| **Blind** | A sensor that could not run (tool missing, LLM unreachable, timeout). A harness problem, never a code failure — and never counted as passed. |
| **Seeded defect** | A fixture with a known mistake (`# expect: <rule>`) that proves the sensor can still fire. |
| **Report** | `.harness/report.md` — the single document the agent reads after every change. |
| **Ledger** | `.harness/ledger.jsonl` — one line per sensor run; the data behind the steering loop. |

Next: [How to use it](02-how-to-use.md)
