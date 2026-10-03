# Review rubric

Shared guide: the coding agent reads it before writing (feedforward), the review agent applies it to the
diff (feedback, `harness/sensors/review.py` with `harness/prompts/review.md`). Linters and the topology /
migrations sensors own everything mechanical; this rubric owns what needs judgement. Only `blocking` rules may
be reported as ERROR.

| id  | blocking | rule |
|-----|----------|------|
| R1  | yes | A new service-to-service call uses `common.service_auth.SignedClient`, and the callee's `TRUSTED_CALLERS` is updated in the same change. Internal endpoints depend on `require_caller()`; only `/healthz` and `/metrics` are open. |
| R2  | yes | Behaviour visible through the API changes only together with a change in `contract/`. A contract test is edited only when the task asked for new behaviour. |
| R3  | yes | Personal data (e-mail, phone, IP address, message text, post bodies) is not logged, and never at INFO or above. Log ids, not content. |
| R4  | yes | A service reads and writes only its own schema with its own role (`<name>_svc`). Data owned by another service is obtained through that service's API or its events, never through its tables. |
| R5  | no  | A new configuration value is added to `docker-compose.yml` with a `${NAME:-default}` and a one-line comment, and to `.env.example`. |
| R6  | no  | No brute-force fixes: no broad `except Exception: pass`, no sleeps or retries added to make a test pass, no assertions loosened to go green. Waiting for an asynchronous effect uses a bounded poll (`eventually()`). |
| R7  | no  | No speculative structure: no new abstraction, flag or layer with a single caller unless the task asked for it. |
| R8  | no  | An event consumer is idempotent (upsert / dedupe on a key) and commits its offset only after its side effect succeeded (auto-commit is caught mechanically by semgrep `kafka-consumer-auto-commit`; review the rest). An event payload change is backward compatible or uses a new topic. |
| R9  | no  | A change to ranking or search behaviour states its expected effect on `make eval` in the commit message or PR. |

## How the reviewer is checked

`make harness-selftest-live` (with an LLM configured) feeds the reviewer seeded diffs from
`harness/sensors/fixtures/review/`: one per inferential-only rule it must flag (R3, R4) and a clean one it must not.
A reviewer that misses one is reported BLIND. Add a seeded diff before promoting a rule to blocking.

## How to dispute a finding

The rubric improves only if wrong findings are recorded. If a review finding is wrong, say why in the commit
message (`review: R4 does not apply — ...`). Repeated disputes of the same rule are the signal to reword it
(`harness/skills/harness-steer/SKILL.md`).
