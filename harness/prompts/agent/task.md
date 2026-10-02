You are working in the haytarar repository, a set of Python microservices run by one docker-compose.yml and
regulated by a harness: guides tell you what to do before you act, sensors tell you what went wrong after.

TASK
{{task}}

BEFORE YOU WRITE CODE
1. Read AGENTS.md and harness/review/RUBRIC.md. The reviewer applies the same rubric to your diff.
2. Pick the skill that matches the task and follow it step by step:
   new deployable → harness/skills/new-service/SKILL.md
   new or changed endpoint → harness/skills/new-endpoint/SKILL.md (contract test first)
   schema change → harness/skills/db-migration/SKILL.md
   new event → harness/skills/new-topic/SKILL.md
3. State in two or three lines what you will change and which contract tests prove it.

LOOP (after every meaningful edit)
1. Run `make harness-fast`.
2. Read .harness/report.md completely and follow harness/skills/harness-report/SKILL.md:
   blocking failures first, re-running only the failing sensor; blind sensors are reported, not worked around.
3. Continue only when the verdict is GREEN.

DONE
- `make up && make harness-integration` is GREEN (unit + contract).
- Go through harness/prompts/agent/done-check.md.
- Summarise: what changed, which tests cover it, blind sensors, advisory findings you did not act on and why.

NEVER
- edit harness.yaml, harness/sensors, fixtures, RUBRIC.md or existing contract tests to get green;
- add sleeps, broad excepts, noqa or nosemgrep to silence a sensor;
- write data inside the repository or call another service without SignedClient.
