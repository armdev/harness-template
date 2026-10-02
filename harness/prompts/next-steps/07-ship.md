# 07 · Ship: everything CI will run, then the pull request

When: the change is done and reviewed.
You should see: the pipeline stage GREEN locally, eval numbers compared with the baseline, a PR description.

---
Prepare this change for a pull request.

1. With the stack up (`make up`), run `make harness-pipeline` — the same stages CI runs — and make sure
   .harness/report.md says GREEN. If not, fix it with harness/prompts/next-steps/05-fix-red.md first.
2. Read .harness/eval-report.md. If a search metric moved, explain why in the PR; update eval/baseline.json
   only if the change is an intended trade-off, and say so.
3. Go through harness/prompts/agent/done-check.md and answer every question.
4. Write the commit message and PR description: what changed and why, how it is tested (which contract and
   unit tests), eval impact, blind sensors, and review findings you chose not to act on with the reason.
