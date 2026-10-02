---
name: harness-steer
description: Maintain the harness itself — add or tune a sensor, a semgrep rule, a seeded defect, a rubric line or a guide, from what the ledger shows. Use when a human asks to improve the harness, or when stats/coverage show a gap. Not for product tasks.
---

# Steer the harness

The harness is a product with its own loop: sensors produce a ledger, the ledger says which guides are weak.
Changes here are made on request of a human, never to get a product change green.

## Read the signals

```bash
make harness-stats      # per sensor: runs, fired, rate, blind, avg seconds, steering hint
make harness-coverage   # guide x sensor matrix; FF-ONLY, FB-ONLY, UNPROVEN, GAP, BAD lines
make harness-selftest   # every seeded defect must fire, every clean fixture must stay quiet
```

| Signal | Meaning | Action |
|---|---|---|
| sensor fires > 30 % | agents keep making this mistake | strengthen the paired guide (skill step, AGENTS.md line, rule message) |
| never fired in 20+ runs | clean code, or a blind sensor | `harness-selftest`; still fires → move it to a later stage; does not → fix it |
| blind > 20 % | broken environment (tool missing, LLM down) | fix the image / plane, not the code |
| FF-ONLY guide | a rule nobody checks | add a computational sensor if the rule is mechanical, or a rubric line |
| FB-ONLY sensor | a lesson nobody teaches | add the rule to a skill or AGENTS.md |
| UNPROVEN sensor | cannot tell quiet from blind | add seeded defects |

## Add a computational rule (preferred over prose)

1. Pick the cheapest home: a compose rule → `harness/sensors/topology_check.py` (new `T<n>`); a code pattern →
   `harness/rules/semgrep/*.yml`; a migrations rule → `migrations_check.py`.
2. Write the message for the agent: what is wrong, where, and the exact fix. The message is a guide too.
3. Seed a defect: a fixture whose first line is `# expect: <rule id>` (a directory fixture uses a `.expect`
   file), plus keep the `# expect: clean` fixture quiet. `make harness-selftest` must show `fires` and `quiet`.
4. Register it in `harness.yaml` (`pairs_with` the guide that teaches it) and check `make harness-coverage`.
5. `make harness-test` (lint + unit tests of the harness), then `make harness-fast` on the real repo: a new rule
   must not fire on the current code unless that is the point of the change.

## Add an inferential rule

Add a line to `harness/review/RUBRIC.md` with `blocking: no`. Promote it to `yes` only after its findings on
real diffs have been checked (count agreed vs. disputed in commit messages). Keep `review-agent` advisory in the
manifest until its precision is measured.

## Release

Bump `template.version` in `harness.yaml` and the `HARNESS_IMAGE` default in `compose.harness.yml`, and add an
entry to `harness/CHANGELOG.md` with the expected first-run impact of new rules on existing projects.
