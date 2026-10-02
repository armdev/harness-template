# Review rubric

Shared guide: the coding agent reads it before writing (feedforward), the review agent applies it to the
diff (feedback). Linters own style; this rubric owns what needs judgement. `blocking` rules may be ERROR.

| id  | blocking | rule |
|-----|----------|------|
| R1  | yes | A new service-to-service call uses the signed client from `common.service_auth`, and the callee's `TRUSTED_CALLERS` is updated in the same change. |
| R2  | yes | Behaviour visible through the API changes only together with a change in `contract/`. A contract test is edited only when the task asked for new behaviour. |
| R3  | yes | Personal data (e-mail, phone, IP address, message text) is not logged outside the activity service, and never at INFO or above. |
| R4  | no  | A new configuration value is added to `docker-compose.yml` with a `${NAME:-default}` and a one-line comment, and to `.env.example`. |
| R5  | no  | No brute-force fixes: no broad `except Exception: pass`, no sleeps or retries added to make a test pass, no assertions loosened to go green. |
| R6  | no  | No speculative structure: no new abstraction, flag or layer with a single caller unless the task asked for it. |
| R7  | no  | A change touching both the Python and Java implementations keeps them behaviourally identical; a Python-only change says so in the commit message. |
