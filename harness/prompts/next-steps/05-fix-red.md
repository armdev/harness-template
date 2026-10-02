# 05 · The harness is RED: fix only that

When: `make harness-fast` or the agent Stop hook reports RED, or CI failed.
You should see: one sensor at a time fixed and re-run in isolation, then a GREEN report; nothing else changed.

---
The harness report is RED. Stop feature work and fix only the blocking failures.

Run `make harness-fast`, then read .harness/report.md completely. For each blocking sensor, in order:
1. Read its "How to fix" line and the guides it lists.
2. Make the smallest change that fixes the cause (the compose key, the migration, the query), never the
   sensor, a fixture, harness.yaml, RUBRIC.md or an existing contract test.
3. Re-run only that sensor with its "Re-run only this" command until it passes.

Then run `make harness-fast` once more and confirm the first line says GREEN. Blind sensors are harness
problems: list them, do not work around them. If a finding looks wrong, quote it, explain why and stop.
