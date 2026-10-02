# 08 · Improve the harness itself (for maintainers)

When: the same mistake keeps coming back, a sensor never fires, or a rule exists only as prose.
You should see: a new or tuned rule with a seeded defect that fires, a clean fixture that stays quiet,
coverage with no new problems, a CHANGELOG entry.

---
You are maintaining the harness, not the product. Follow harness/skills/harness-steer/SKILL.md.

1. Run `make harness-stats`, `make harness-coverage` and `make harness-selftest`. Summarise: which sensors fire
   most (the guide is weak), which never fire, which are blind, and which guides are FF-ONLY.
2. Propose at most three changes, ordered by value, each as: signal → change → which file. Prefer turning prose
   into a computational check (topology rule, semgrep rule, migrations rule) over adding more prose.
3. Wait for my choice. Then implement it with a seeded defect (`# expect: <rule id>`), keep the clean fixture
   quiet, register it in harness.yaml with `pairs_with`, and run `make harness-test`, `make harness-selftest`,
   `make harness-coverage` and `make harness-fast`.
4. Add an entry to harness/CHANGELOG.md with the expected first-run impact on existing projects.
