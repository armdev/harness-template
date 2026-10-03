# AGENTS.md

This project is regulated by air-harness: guides tell you how to work here, sensors tell you what went wrong.

## How you get feedback
1. After each change: `make harness-fast` (static sensors, no network, < 1 min; plus an advisory review).
2. Read `.harness/report.md`. Fix **blocking failures** first; each one says how to fix it and how to re-run it alone.
3. **Blind sensors** in the report are harness problems, not your code: report them, do not work around them.

## Skills
| Task | Skill |
|---|---|
| a sensor failed, or before you say "done" | `harness/skills/harness-report/SKILL.md` |
| change the harness itself (only when asked) | `harness/skills/harness-steer/SKILL.md` |

## What reviewers check
`harness/review/RUBRIC.md` — read it before writing; the review agent applies the same rubric to your diff.

## Never
Edit `harness.yaml`, `harness/sensors/`, fixtures or `RUBRIC.md` to make a sensor pass; add `noqa` or `nosemgrep` to
silence one; write data into the repository.
