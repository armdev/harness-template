---
name: harness-report
description: Read .harness/report.md and fix what the harness found. Use after every change, whenever make harness-fast or harness-integration fails, and before declaring a task done.
---

# Act on the harness report

The harness is your feedback loop. `make harness-fast` runs the static sensors (no network, < 1 min) and the
advisory review agent, then writes `.harness/report.md`. Read the whole report before your next edit.

## Order of work

1. **Verdict line.** `GREEN` → continue. `RED` → stop feature work until it is green again.
2. **Blocking failures**, one sensor at a time. Each section gives *How to fix*, the *Guides* that teach the rule,
   the sensor output, and *Re-run only this* — use that command, not the whole stage, while you iterate.
   - `topology` → fix `docker-compose.yml`; each finding names the key. Guide: `harness/skills/new-service/SKILL.md`.
   - `migrations` → never edit a committed migration; add a new one. Guide: `harness/skills/db-migration/SKILL.md`.
   - `ruff` → `ruff check --fix` handles most; never add `noqa` without a reason on the same line.
   - `semgrep-local` → the rule message says what to write instead. Never add `nosemgrep` in `services/`.
   - `unit` / `contract` → the tests are the spec. Fix the implementation. Changing a test is allowed only when
     the task asked for that new behaviour (rubric R2), and you say so in the commit message.
3. **Blind sensors** (BLIND / TIMEOUT) are the harness's problem, not your code: report them to the human in
   your summary. Do not disable, skip or work around them, and do not count them as passed.
4. **Advisory findings** (review agent, eval) are judgement calls. Fix ERRORs you agree with; for ones you
   disagree with, write `review: <rule> does not apply — <why>` in the commit message.
5. **Warnings** on passing sensors: fix them if your change introduced them.

## Done means

- `make harness-fast` is GREEN and you have read the report from *this* revision (no `stale` markers).
- With the stack up (`make up`): `make harness-integration` is GREEN.
- Your summary lists any blind sensors and any advisory findings you chose not to act on.

## Never

Edit `harness.yaml`, sensors, fixtures, `RUBRIC.md` or contract tests to make a failure go away. If you believe a
sensor is wrong, say so and stop — that is a change to the harness, made by a human
(`harness/skills/harness-steer/SKILL.md`).
