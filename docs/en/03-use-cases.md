# 3. Use cases

Each use case names the actor, the trigger, what the harness does and what "done" looks like. Prompts are in
`harness/prompts/next-steps/` (`./help.sh prompt <n>`).

## UC-1 · Onboard a coding agent to an unfamiliar repository

- **Actor:** developer + agent · **Prompt:** 01
- **Flow:** the agent reads `AGENTS.md`, the rubric and the skill list; explains the topology from
  `docker-compose.yml`; runs `make harness-list` and `make harness-fast`.
- **Harness role:** guides only (nothing changes). The report shows the agent what "green" means here.
- **Done:** a short, correct tour: services, call graph, data ownership, events, sensors and which skill fits
  which task.

## UC-2 · Implement a feature contract-first

- **Actor:** agent · **Prompt:** 02 · **Skill:** `new-endpoint`
- **Flow:** write the contract test → watch it fail → implement in the owning service behind
  `require_caller()` → forward in the gateway → loop on `make harness-fast` → `make harness-integration`.
- **Sensors involved:** ruff, semgrep (`sql-built-from-strings`, `unsigned-service-call`), contract, review (R2).
- **Done:** contract suite GREEN; the PR says which tests prove the behaviour.

## UC-3 · Change the database schema safely

- **Actor:** agent · **Prompt:** 03 · **Skill:** `db-migration`
- **Flow:** a new `V<n>__name.sql` with the `GRANT` for the owning role; backward-compatible columns.
- **Sensors involved:** `migrations` — M1 naming, M2 unique version, **M3 append-only** (an edited committed
  migration is caught against `MIGRATIONS_BASE`), M4 granted, M5 no gaps; semgrep `ddl-outside-migrations`.
- **Done:** `migrate` exits 0 on `make up`; contract GREEN.

## UC-4 · Add a new service

- **Actor:** agent · **Prompt:** 04 · **Skill:** `new-service`
- **Flow:** add the compose entry first and run `make harness-fast` *before writing code*: the topology sensor
  lists every missing piece, each with the exact compose key to change.
- **Sensors involved:** topology T1 (caller trusted), T2 (key provisioned and mounted), T4/T5 (startup order),
  T7 (alert rules), T8 (variable documented), T9 (no data in the repo); prom-rules in the pipeline.
- **Done:** topology clean, new endpoint has contract tests, alerts exist.

## UC-5 · Recover from a RED report

- **Actor:** agent (or the Stop hook / CI) · **Prompt:** 05 (`./help.sh prompt fix-red` embeds the report)
- **Flow:** blocking sensors in order; smallest fix at the cause; `make harness-one s=<id>` until it passes.
- **Guardrails:** the agent may not edit `harness.yaml`, sensors, fixtures, the rubric or existing contract
  tests to go green; blind sensors are reported, not worked around.
- **Done:** report GREEN on the current revision (no *stale* markers).

## UC-6 · Stop an agent from declaring "done" too early

- **Actor:** Claude Code Stop hook (`harness/hooks/agent-stop.sh`)
- **Flow:** the agent tries to finish with uncommitted changes → the hook runs `make harness-static` → RED →
  exit code 2 → the agent is sent back with the head of the report. The next attempt is always allowed
  (`stop_hook_active`), so a broken harness cannot loop the agent.
- **Done:** the agent finishes only with static sensors GREEN, or explicitly reports why not.

## UC-7 · Review a change before commit / PR

- **Actor:** developer or agent · **Prompt:** 06
- **Flow:** apply `RUBRIC.md` rule by rule (R1–R9) to the uncommitted diff; check contract/migration/config
  coverage; include anything RED or BLIND.
- **Automated twin:** the `review-agent` sensor applies the same rubric through an LLM on every fast loop
  (advisory).
- **Done:** "ready", or a list of blocking items with file:line and the fix.

## UC-8 · Ship and keep CI green

- **Actor:** developer / agent / CI · **Prompt:** 07
- **Flow:** `make harness-pipeline` locally (identical to CI) → read `.harness/eval-report.md` → explain any
  search-metric change → done-check → PR. CI runs `./run.sh --full` and attaches the report.
- **Done:** pipeline GREEN; eval within `EVAL_TOLERANCE` of `eval/baseline.json` or the change is justified.

## UC-9 · Measure search quality

- **Actor:** CI (pipeline) or developer (`make eval`)
- **Flow:** seed `eval/corpus.yaml` once per corpus version through the public API → run every query →
  recall@5 and MRR@10 (+ optional LLM judge@1 with `JUDGE_BASE_URL`) → compare with `eval/baseline.json`.
- **Done:** no metric below baseline − tolerance; per-query table in `.harness/eval-report.md`.

## UC-10 · Improve the harness from data (maintainers)

- **Actor:** maintainer · **Prompt:** 08 · **Skill:** `harness-steer`
- **Flow:** `harness-stats` (what fires often / never / is blind) → `harness-coverage` (FF-ONLY guides,
  FB-ONLY sensors, UNPROVEN sensors) → propose ≤ 3 changes → implement with a seeded defect and a quiet clean
  fixture → `harness-test`, `harness-selftest`, `harness-coverage` → CHANGELOG entry.
- **Done:** the new rule fires on its fixture, stays quiet on clean code and on the real repository.

## UC-11 · Adopt the harness in another project

- **Actor:** platform team
- **Flow:** copy `harness/`, `harness.yaml`, `compose.harness.yml`, `harness.mk`, `AGENTS.md`, `CLAUDE.md`,
  `.claude/`, `.githooks/`, `pyproject.toml`; `include harness.mk`; add `x-harness` paths to the project's
  compose file; `make harness-coverage && make harness-selftest && make harness-fast`.
- **Versioning:** the runner image is pinned (`HARNESS_IMAGE`); the manifest and guides belong to the project;
  `template.version` records which upstream version it was reconciled with.

Next: [Implemented architecture](04-architecture.md)
