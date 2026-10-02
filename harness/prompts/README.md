# Prompts

Prompts are guides too: versioned with the harness, reviewed like code, and paired with the sensors that check
what they ask for.

| File | Used by | Purpose |
|---|---|---|
| `review.md` | `harness/sensors/review.py` (system prompt) | turn the rubric into structured findings for the agent |
| `judge.md` | `eval/run_eval.py` (system prompt, `JUDGE_BASE_URL` set) | grade search results 0–3 |
| `agent/task.md` | a human or orchestrator starting a coding agent | the harness loop the agent must follow for a task |
| `agent/fix-red.md` | hook / orchestrator when `.harness/report.md` is RED | focus the agent on blocking failures only |
| `agent/done-check.md` | the agent, before it reports a task as done | self-review against the rubric and the definition of done |
| `next-steps/NN-*.md` | you, via `./help.sh prompt NN` | ready-to-paste prompts for the usual next steps, in order: explore, first endpoint, schema change, new service, fix RED, review, ship, improve the harness |

`./help.sh prompts` lists them; `./help.sh prompt <n>` prints the prompt part (below the `---` line) of a
next-step file, `./help.sh prompt task "<task>"` fills `agent/task.md`, `./help.sh prompt fix-red` fills
`agent/fix-red.md` with the current `.harness/report.md`.

Placeholders are written `{{like_this}}`; `help.sh` fills the known ones. Keep prompts short and imperative: every
line should change what the model does. When a sensor keeps firing on the same mistake, fix the guide (skill,
AGENTS.md) first and the prompt second — prompts are the least durable place for a rule.
