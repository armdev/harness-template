Before you report the task as done, answer each question with yes, no or n/a and one line of evidence
(file:line, command output). Fix every "no" first.

1. R1  Every new service-to-service call uses SignedClient, and the callee's TRUSTED_CALLERS lists the caller?
2. R2  Every API behaviour change has a contract test, and no existing contract test was weakened?
3. R3  No personal data or post content is logged?
4. R4  Each service touches only its own schema with its own role?
5. R5  Every new setting is `${NAME:-default}` with a comment in compose and listed in .env.example?
6. R6  No sleeps, broad excepts or loosened assertions were added to get green?
7. R7  No abstraction, flag or layer with a single caller that the task did not ask for?
8. R8  Consumers are idempotent and commit after the side effect; event changes only add fields?
9. `make harness-fast` is GREEN on this revision (no "stale" markers in .harness/report.md)?
10. `make harness-integration` is GREEN with the stack up?
11. Your summary names every blind sensor and every advisory finding you did not act on?
