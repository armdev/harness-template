# 01 · Get to know the repository

When: first session with a coding agent in this repo. Nothing is changed.
You should see: a short tour that names the services, the call graph, the harness loop and the skills.

---
You are new to this repository. Do not change any file in this session.

1. Read AGENTS.md, harness/review/RUBRIC.md and the list of skills in harness/skills/.
2. Read docker-compose.yml and explain in at most 15 lines: which services exist, who calls whom (and how the
   call is authenticated), which service owns which data, and which events flow over Kafka.
3. Run `make harness-list` and `make harness-fast`, read .harness/report.md, and explain what each sensor
   checks and which stage it runs in.
4. Finish with: the three files you would read first for a feature task, and which skill applies to
   (a) a new endpoint, (b) a new column, (c) a new service.
