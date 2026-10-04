# 7. Demo — screenshots and walkthrough

Everything on this page was captured from a real run of the product: a clean `./run.sh --full` on Docker 29 /
Compose v5, the real API in a browser, real Prometheus, and a deliberate mistake handed to the harness.
Nothing is mocked.

## Walkthrough (46 s)

![air-harness demo: run, API, observability, a RED report, the Stop hook, GREEN, prompts](../assets/demo-en.gif)

1. `./run.sh` starts the stack and smoke-tests it · 2. `--full` runs every harness stage · 3. it prints every URL
· 4–6. the public API in Swagger UI: create a post, find it through search · 7–8. Prometheus scrapes every
service · 9–11. an agent adds a service and an f-string SQL query → RED report → the Stop hook sends it back ·
12. after the fix the fast loop is GREEN · 13. guided prompts for the next step.

## 1. Run it — `./run.sh --full`

**Preflight, build, start, smoke test.** Every service healthy, then a post is created, read back and found by
search through Kafka.

![run.sh: preflight, start, smoke test](../assets/terminal-run-start.png)

**The harness proves itself, then checks the code.** Seeded defects fire, clean fixtures stay quiet, then the
pre-commit, integration and pipeline stages run. The review agent is BLIND here because no LLM was configured —
advisory, so it never blocks.

![run.sh: selftest and all stages GREEN](../assets/terminal-run-harness.png)

**Where everything is.** Every reachable URL, how to reach the internal services, reports and next steps.

![run.sh: URLs and next steps](../assets/terminal-run-urls.png)

## 2. The API — http://localhost:8080

The root redirects to Swagger UI. The gateway is the only public service; every call behind it is signed.

![Swagger UI overview](../assets/swagger-overview.png)

| Create a post (201) | Search finds it (indexed via Kafka) |
|---|---|
| ![POST /api/posts → 201](../assets/swagger-create-post.png) | ![GET /api/search → 200](../assets/swagger-search.png) |

ReDoc at `/redoc`:

![ReDoc](../assets/redoc.png)

## 3. Observability — http://localhost:9090

| Every service scraped and UP | Alert rules per service (topology T7 enforces them) |
|---|---|
| ![Prometheus targets](../assets/prometheus-targets.png) | ![Prometheus alerts](../assets/prometheus-alerts.png) |

Request rate by service and status (`sum by (job, status) (rate(http_requests_total[1m]))`) — 422s are the
validation failures the traffic generator sent on purpose:

![Prometheus graph](../assets/prometheus-graph.png)

## 4. The harness catches an agent's mistake

The scenario: an agent adds a `notify` service that calls `content`, and builds a SQL query with an f-string.
It forgets `TRUSTED_CALLERS`, the service key, alert rules and the new variable in `.env.example`.

**The static sensors go RED** in seconds, without network:

![make harness-static: RED](../assets/terminal-harness-static-red.png)

**The report says exactly what and how to fix** — each finding names the compose key, the guide that teaches the
rule, and the command to re-run only that sensor:

![.harness/report.md RED](../assets/report-red.png)

**The agent cannot declare "done".** The Claude Code Stop hook runs the static sensors on uncommitted changes and
exits 2 with the report, so the agent goes back to work:

![Stop hook](../assets/terminal-stop-hook.png)

**After the fix**, the fast loop is GREEN again:

| `make harness-fast` | `.harness/report.md` |
|---|---|
| ![make harness-fast GREEN](../assets/terminal-harness-fast-green.png) | ![report GREEN](../assets/report-green.png) |

## 5. Learn it and hand it to an agent — `./help.sh`

| `./help.sh` | `./help.sh prompts` |
|---|---|
| ![help.sh](../assets/terminal-help.png) | ![help.sh prompts](../assets/terminal-prompts.png) |

`./help.sh prompt 02` prints a ready-to-paste prompt (`claude "$(./help.sh prompt 02)"`):

![help.sh prompt 02](../assets/terminal-prompt-02.png)

## 6. The web console

`./run.sh --console` → http://127.0.0.1:8090. Captured against the running stack with Chromium (Playwright).

**Overview** — stack health, the verdict, the loop:

![console overview](../assets/console-overview.png)

**API** — forms generated from the gateway's OpenAPI; here a post is created and found through search:

![console API playground](../assets/console-api.png)

**Harness** — every stage one click away; each sensor with its last result, selftest verdict and history:

![console harness](../assets/console-harness.png)

**Agent** — a real run: the prompt goes to `claude -p`, its answer streams in, and the timeline shows the
pre-commit run its Stop hook triggered when it finished:

![console agent run](../assets/console-agent-run.png)

**Guides** — AGENTS.md, skills, rubric and prompts, rendered:

![console guides](../assets/console-guides.png)

Back to the [documentation index](../README.md) · previous: [Low-level design](06-low-level-design.md)
