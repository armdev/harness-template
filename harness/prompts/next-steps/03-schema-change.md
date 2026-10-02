# 03 · Schema change: tags on posts

When: you want to see the migrations sensor and the database rules in action.
You should see: a new V4 migration (never an edit of V1–V3), grants in the same file, contract tests for tags,
search indexing the tags.

---
Task: posts get optional tags. `POST /api/posts` accepts `"tags": ["kafka", "flyway"]` (0–5 tags, each
1–32 chars of a-z0-9-); every post response includes `"tags"`; `GET /api/search?tag=<tag>` filters by tag.

Follow harness/skills/db-migration/SKILL.md for the schema (a new migration in db/migrations; content and
search each change their own schema), harness/skills/new-topic/SKILL.md step 5 for the event (only add the
field), and harness/skills/new-endpoint/SKILL.md for the API (contract tests first).

Keep it backward compatible: old posts have an empty tag list. Run `make harness-fast` after each edit and
fix blocking failures first. Done when `make up && make harness-integration` is GREEN; summarise with
harness/prompts/agent/done-check.md.
