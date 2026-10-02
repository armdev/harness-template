# 06 · Review a change before you commit or open a PR

When: a change is finished (yours or an agent's) and you want a second look against the team's rules.
You should see: rubric findings with file:line and a concrete fix, or a short "no findings".

---
Review the uncommitted changes in this repository (`git diff HEAD` plus untracked files) as a strict reviewer.

1. Apply harness/review/RUBRIC.md rule by rule (R1–R9). For each finding give: rule id, file:line, what is
   wrong in one sentence, and the exact fix. Do not report style issues the linters own.
2. Check that every API behaviour change has a contract test, every schema change is a new migration with
   grants, and every new setting is in docker-compose.yml with a default and in .env.example.
3. Run `make harness-fast` and include anything RED or BLIND from .harness/report.md.
4. End with a verdict: "ready", or "not ready" with the list of blocking items. Do not edit any file.
