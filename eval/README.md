# Search evaluation

Guide for the `eval` sensor (`harness.yaml`, stage `pipeline`, blocking on recall@5 and MRR@10).

- `corpus.yaml` — documents and queries with their relevant documents. Bump `version` when you change docs.
- `baseline.json` — the agreed numbers. A change that lowers a metric by more than `EVAL_TOLERANCE` fails.
- `make eval` (stack up) seeds the corpus through the public API, runs every query and writes
  `.harness/eval-report.md` (per-query table, weakest queries) and `.harness/eval-results.json`.

Metrics: **recall@5** (share of relevant docs in the top five), **MRR@10** (how high the first relevant doc
ranks). With `JUDGE_BASE_URL` set, an LLM grades the top hit 0–3 against `harness/prompts/judge.md`
(**judge@1**, inferential: compare it only with itself on the same model; a drop is reported, never blocks).

When a ranking change lowers a metric: explain the drop in the PR. If it is the intended trade-off, copy
`.harness/eval-results.json` over `baseline.json` in the same change. Never edit `corpus.yaml` queries to make
a change pass.
