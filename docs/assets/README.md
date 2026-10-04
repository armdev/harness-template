# Documentation assets

Screenshots and the demo GIFs used by `docs/en/07-demo.md` and `docs/ru/07-demo.md`.

- Captured on 2026-10-02 from commit `2fc679e` with a clean `DATA_DIR`: `./run.sh --full` (Docker 29.6, Compose 5.3).
- Swagger UI, ReDoc and Prometheus images re-captured on 2026-10-03 after prompts 02–04 (list by author, tags,
  the `notify` service) so they show the current API and all four scraped services.
- Terminal images: real sessions recorded through a pseudo-terminal (`script`), rendered from their ANSI output;
  Docker Compose's live progress is collapsed to its final state and the long selftest list is shortened.
- Browser images: Chromium (Playwright) against the running stack — Swagger UI, ReDoc, Prometheus — after a few
  minutes of generated API traffic.
- The RED / Stop-hook images come from a deliberate, reverted change (a `notify` service without trust, key,
  alerts or documented variable, plus an f-string SQL query).
- `demo-en.gif` / `demo-ru.gif`: the same screenshots in sequence with captions (1200×760, ~46 s, ~0.9 MB each).

- `console-*.png`: the web console (`./run.sh --console`) on 2026-10-04, Chromium (Playwright) against the running
  stack; the agent run is a real `claude -p` call with a read-only prompt.

Re-capture them when the output of `run.sh`, the report format or the UI changes noticeably.
