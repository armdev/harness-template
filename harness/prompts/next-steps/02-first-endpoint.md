# 02 · First feature: list posts by author (contract first)

When: you want to watch the full loop on a small, real change.
You should see: a new contract test failing first, then implementation in content + gateway, `make harness-fast`
GREEN, `make harness-integration` GREEN.

---
Task: add `GET /api/posts?author=<author>&limit=<n>` to the public API. It returns
`{"author": "...", "posts": [<post>, ...]}`, newest first, `limit` 1–50 (default 20), 422 for a missing or
invalid author.

Follow harness/skills/new-endpoint/SKILL.md step by step:
1. Write the contract tests in contract/test_posts.py first and run `make contract` to see them fail for the
   right reason (the stack is up: `make up`).
2. Implement it in services/content (it owns posts) behind require_caller(), with SQL parameters only.
3. Forward it in services/gateway and validate the query parameters there too.
4. After each edit run `make harness-fast` and act on .harness/report.md (harness/skills/harness-report/SKILL.md).
5. Done when `make harness-integration` is GREEN. Then go through harness/prompts/agent/done-check.md and
   summarise what changed, which tests prove it, and any blind sensors.
