# 6. Low-level design

## 6.1 Runner (`harness/harness.py`)

Single file, standard library + PyYAML. The same script runs in the sensor containers and on the host.

### Configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `HARNESS_ROOT` | `.` | repository root (`/work` in containers) |
| `HARNESS_OUT` | `$HARNESS_ROOT/.harness` | output directory (`/out` in containers) |
| `HARNESS_MANIFEST` | `harness.yaml` | manifest path relative to the root |
| `HARNESS_PLANE` | `all` | default `--plane` (`static` / `live` set by the containers) |
| `HARNESS_TIMEOUT` | `900` (300 in compose) | seconds per sensor command |
| `HARNESS_TAIL_LINES` | `60` | lines of sensor output kept per result |

### Verbs and exit codes

| Verb | Does | Exit codes |
|---|---|---|
| `run --stage S [--plane P] [--only ID]` | runs the selected sensors, writes results, ledger, report | 0 green · 1 a blocking sensor failed **or is blind** · 2 unknown `--only` id · 3 `--only` sensor belongs to another plane |
| `selftest [--plane P] [--only ID]` | runs every sensor's `selftest.run` on each fixture; only the sensors of its plane (`HARNESS_PLANE`), the others print where they are proven | 0 all fire / stay quiet · 1 a sensor is blind or noisy |
| `coverage` | guide × sensor matrix, consistency checks | 0 consistent · 1 problems |
| `stats [--min-runs N] [--window W]` | steering table from the ledger and the last selftest verdicts (`N` 20, `W` 10) | 0 |
| `list` | one line per sensor | 0 |

### Sensor execution

```mermaid
flowchart TD
    A["select sensors:<br/>stage in stages, plane in planes, id = only"] --> B["for each: sh -c run<br/>cwd=ROOT, timeout=HARNESS_TIMEOUT"]
    B --> C{exit code}
    C -->|0| P[pass]
    C -->|126 / 127| U[unavailable → BLIND]
    C -->|timeout| T[timeout → BLIND]
    C -->|125| K[skipped → SKIP<br/>advisory only; blocking → BLIND]
    C -->|other| F[fail]
    P & U & T & F & K --> W["write results/ID.json<br/>append ledger.jsonl"]
    W --> R[write report.md<br/>union of latest results of the stage]
```

A sensor is **any command**. Contract: exit 0 = pass; 125 = deliberately not configured here (e.g. no LLM) — the
runner reports SKIP, which never fails a stage, but only for advisory sensors (a blocking sensor that exits 125 is
BLIND); 126/127 = cannot run (BLIND, never a code failure); anything else = fail. Findings are printed one per line starting with `ERROR` or `WARN`, followed
by indented `what:` / `fix:` lines. `WARN` lines (and their next two indented lines) of a *passing* sensor are
still surfaced in the report.

### Result file — `.harness/results/<id>.json`

```json
{"id": "topology", "status": "fail", "rc": 1, "seconds": 0.11, "rev": "cdbf004",
 "stage": "pre-commit", "plane": "static", "kind": "computational", "category": "architecture",
 "blocking": true, "ts": 1790966386,
 "output": "<last HARNESS_TAIL_LINES lines>", "warnings": ["WARN T6 ...\n      what: ...\n      fix: ..."]}
```

`status` ∈ `pass | fail | unavailable | timeout | skipped`. The **ledger** (`.harness/ledger.jsonl`) appends the same
record without `output` and `warnings`, one line per run.

### Report — `.harness/report.md`

Built from the latest result of every sensor declared for the stage (so the static and live containers, run
separately, produce one report):

1. Title: stage, current revision, verdict — **RED** if any blocking sensor failed or is blind, else **GREEN**.
2. *Blocking failures* — per sensor: kind, category, `fix_hint` (*How to fix*), paths of the paired guides,
   *Re-run only this* command (`make harness-one s=<id>` for container planes, the `python3 harness/harness.py …`
   command for the host plane), the output tail.
3. *Advisory findings* — same layout for non-blocking failures.
4. *Blind sensors* — status and the first 300 characters of output.
5. *Skipped (not configured)* — the sensor's own last output line, which says how to enable it.
6. *Warnings* — WARN blocks of passing sensors.
7. *Not run in this stage yet* — declared sensors without a result (e.g. another plane).
8. *Passed*.

A result whose `rev` differs from the current revision is marked **stale**.

### Selftest

For each sensor with a `selftest` block, every entry of `selftest.fixtures` (files, or directories whose
expectation is in a `.expect` file) is run through `selftest.run` with `{fixture}` substituted.

| First line of the fixture | Passes when |
|---|---|
| `# expect: <text>` | exit code ∉ {0, 126, 127} **and** `<text>` appears in the output → `fires` |
| `# expect: clean` | exit code 0 → `quiet` |
| no expectation | exit code ∉ {0, 126, 127} |

Otherwise the line is `BLIND` / `NOISY` and the verb exits 1. Fixtures are excluded from normal linting
(`pyproject.toml` `extend-exclude`).

### Coverage checks

Problems (exit 1): `MISSING` guide path or selftest fixtures · `BAD` unknown kind/category/stage/plane ·
`DANGLING` `pairs_with` to an unknown guide · `DUP` duplicate sensor id · `GAP` a category without any sensor.
Information: `FF-ONLY` guide no sensor checks · `FB-ONLY` sensor no guide teaches · `RISK` inferential and
blocking · `UNPROVEN` static computational sensor without seeded defects.

### Stats — steering hints

Per sensor: runs, fired (= failed), rate, blind, average seconds, skipped. Skipped runs are counted apart and left
out of every rate (a sensor that only ever skipped is listed as *never ran*). Hint order: *blind in > 20 % of the last
`--window` runs (default 10, skips included)* → fix the environment; *rate > 30 %* → strengthen the paired guide;
*never fired in ≥ `--min-runs` runs* → read `.harness/selftest.json` (written by every selftest): *proven* → the code
is clean there, consider a later stage; *blind/noisy* → fix the sensor; no verdict → run selftest.

## 6.2 Manifest schema (`harness.yaml`)

```yaml
harness: 1
template: { name: py-services-pg-kafka, version: 0.5.1 }
categories: [maintainability, architecture, behaviour]
guides:
  - id: <unique>                 # referenced by sensors.pairs_with
    path: <file or directory>    # must exist (coverage)
    kind: computational | inferential
    category: [<category>, ...]
sensors:
  - id: <unique>
    kind: computational | inferential
    category: <category>
    plane: static | live | host
    stages: [pre-commit | integration | pipeline | continuous, ...]
    blocking: true | false       # default true
    run: <shell command, cwd = repo root>
    pairs_with: [<guide id>, ...]
    fix_hint: <one line shown in the report>
    selftest:                    # optional
      fixtures: <directory>
      run: <command with {fixture}>
```

## 6.3 Sensor containers (`compose.harness.yml`, `harness.mk`)

Both services use `image: ${HARNESS_IMAGE:-air-harness-runner:0.5.1}`, profile `harness`,
`user: ${HARNESS_UID}:${HARNESS_GID}` (set by make to the invoking user), `read_only: true`, `tmpfs: /tmp`,
`cap_drop: [ALL]`, `no-new-privileges`, the repository at `/work:ro` and `./.harness` at `/out`.

| Service | Network | Extra environment |
|---|---|---|
| `harness` | `network_mode: none` | `HARNESS_PLANE=static`, `MIGRATIONS_BASE` |
| `harness-live` | project network + `host.docker.internal` | `HARNESS_PLANE=live`, `LLM_*`, `REVIEW_MODEL`, `REVIEW_DIFF_BASE`; `/tmp` mounted `exec` (pip-audit runs a throwaway venv there) |

Every container target has the order-only prerequisite `| $(OUT_DIR)`, which creates `.harness/` as the
invoking user *before* docker would create the bind-mount source as root. `harness-one` runs the sensor in
`harness`; on exit code 3 (other plane) it re-runs it in `harness-live`.

## 6.4 Topology sensor (`topology_check.py`)

Input: a compose file (`--strict` makes warnings fail, used by selftest). Parses YAML with `SafeLoader`
(so `<<` merges are resolved and `depends_on` is the effective one) and scans the raw text for variables
(comments stripped). Paths for T7/T8 come from the compose file itself: `x-harness: {alerts, env_example}`.
Services in a dev profile (`TOPOLOGY_DEV_PROFILES`, default `admin,local-llm,e2e,tools`) are tooling and are
skipped by T1, T4–T7, T9, T10.

| Rule | Severity | Check |
|---|---|---|
| T1 caller-trusted | ERROR | for every `http(s)://<svc>:<port>` in a service's env (defaults resolved): if `<svc>` has `TRUSTED_CALLERS`, the caller must be in it |
| T2 key-provisioned | ERROR / WARN | key subpaths mounted from `service-keys` must be in the `service-keys` entrypoint list (after `/keys`); every trusted caller must have a key; a caller must mount its own key; WARN if a service signs as another identity |
| T3 default-drift | ERROR / WARN | one variable, one default; WARN when `:-` and `-` are mixed |
| T4 migrate-first | ERROR | a service with `DB_DSN` depends on `migrate` |
| T5 topics-first | WARN | a service with `KAFKA_BOOTSTRAP` depends on `kafka-init` |
| T6 pinned-images | WARN | no untagged / `:latest` images; flags frozen registries (`bitnamilegacy/`) |
| T7 alerts-present | ERROR | every long-running (`restart` set), built, profile-less service has `job="<name>"` in the alerts file |
| T8 env-documented | ERROR | every `${VAR}` read by compose is a `VAR=` line in the env example |
| T9 data-outside-repo | ERROR | no writable bind mount from the repository (`./…`) |
| T10 callee-verifies | ERROR | a service with `TRUSTED_CALLERS` mounts the `service-keys` subpath `public`; without it it can verify no signature and rejects every call with 401 (checked when `service-keys` exists) |

Output format: `SEV  RULE  location` / `what:` / `fix:`; last line `topology: N services, E errors, W warnings`.

## 6.5 Migrations sensor (`migrations_check.py`)

| Rule | Severity | Check |
|---|---|---|
| M1 naming | ERROR | file name matches `^(V<n>|R)__<snake_case>.sql$` (dotfiles ignored) |
| M2 unique-version | ERROR | each `V<n>` once |
| M3 append-only | ERROR | `git diff --name-status $MIGRATIONS_BASE -- <dir>` shows no `M`/`D` for a `V` file (default base `HEAD`; CI: `origin/main`; skipped outside git) |
| M4 granted | ERROR | every `CREATE TABLE x` has a `GRANT … ON x TO …` in the same file (comments stripped; grant lists split on commas) |
| M5 no-gaps | WARN | versions 1…max are contiguous |

## 6.6 Review sensor (`review.py`)

```mermaid
sequenceDiagram
    participant R as review.py
    participant G as git
    participant L as LLM (OpenAI-compatible)
    R->>G: git diff, staged, in scope
    alt nothing staged
        R->>G: git diff HEAD plus untracked files, in scope
    end
    R->>R: truncate to REVIEW_MAX_DIFF_CHARS (60000)
    R->>L: POST /chat/completions, system = prompts/review.md, user = RUBRIC + DIFF, temperature 0
    L-->>R: JSON findings (code fences and think blocks tolerated)
    R->>R: print ERROR/WARN lines → exit 1 if any ERROR
```

Scope: `services libs db contract docker-compose.yml infra`. `REVIEW_DIFF_BASE` set → `git diff <base>`.
`LLM_BASE_URL` empty (the default: the review is opt-in) → exit 125 (SKIP, with how to enable it). Configured but
unreachable endpoint, or a reply without a JSON object → exit 127 (BLIND). `LLM_NO_THINK=true` sends
`chat_template_kwargs.enable_thinking=false` (ignored by servers that do not support it). Finding schema:
`{severity: ERROR|WARN, rule, file, line, what, fix}`.

## 6.7 Stop hook (`harness/hooks/agent-stop.sh`)

```mermaid
flowchart TD
    A[stdin: hook JSON] --> B{stop_hook_active?}
    B -->|true| OK[exit 0]
    B -->|false| C{"uncommitted changes?<br/>git status --porcelain"}
    C -->|no| OK
    C -->|yes| D{docker available?}
    D -->|no| OK
    D -->|yes| E["make -s harness-static"]
    E -->|GREEN| OK
    E -->|RED| F["stderr: head of report.md<br/>exit 2, the agent continues"]
```

## 6.8 Signed service-to-service calls (`libs/common/common/service_auth.py`)

**Keys.** `service-keys` runs `python -m common.keygen /keys gateway content search notify graph web chat` as root: per service
`/keys/<name>/private.pem` (PKCS#8 Ed25519, mode 0400, owner uid 10001, directory 0500) and
`/keys/public/<name>.pem` (0444). Idempotent: existing keys are kept. Each service mounts
`subpath: <name>` at `/run/keys/self` and `subpath: public` at `/run/keys/public`, read-only.

**Canonical string and headers.**

```
canonical = METHOD + "\n" + PATH[?QUERY] + "\n" + UNIX_TIMESTAMP + "\n" + hex(SHA-256(body))
X-Caller:    <service name>
X-Timestamp: <unix seconds>
X-Signature: base64(Ed25519.sign(private_key, canonical))
X-Request-ID: <propagated request id>
```

```mermaid
sequenceDiagram
    participant GW as gateway (SignedClient)
    participant C as content (require_caller)
    GW->>GW: body = request.read(), ts = now
    GW->>GW: sig = Ed25519 sign of the canonical string
    GW->>C: HTTP + X-Caller/X-Timestamp/X-Signature/X-Request-ID
    C->>C: headers missing → 401
    C->>C: caller ∉ TRUSTED_CALLERS → 403
    C->>C: clock skew above MAX_CLOCK_SKEW (60 s) → 401
    C->>C: verify with /run/keys/public/<caller>.pem, fail → 401
    C-->>GW: handler result (request.state.caller = caller)
```

The verifier caches public keys per caller; `/healthz` and `/metrics` are not protected. Known limit: no nonce
store, so a captured request can be replayed inside the skew window (internal network only).

## 6.9 Telemetry (`libs/common/common/telemetry.py`)

`create_app(service, **fastapi_kwargs)`:

- JSON log lines on stdout: `ts, level, service, logger, msg, request_id[, exc]`; level from `LOG_LEVEL`;
  uvicorn access log disabled.
- Middleware: request id from `X-Request-ID` or a new UUID, echoed in the response; metrics per *route
  template* (`/api/posts/{post_id}`, unmatched → `unmatched`); `/metrics` and `/healthz` excluded.
- `http_requests_total{service,method,route,status}` (counter),
  `http_request_duration_seconds{service,method,route}` (histogram).
- `GET /healthz` → `{"status":"ok","service":…}`; `GET /metrics` → Prometheus text format.

### Event consumer (`libs/common/common/events.py`)

`EventConsumer(topic, handler, bootstrap=…, group_id=…, name=…)` runs one background thread; the
`confluent_kafka.Consumer` is created in `start()` with `enable.auto.commit=False`, `auto.offset.reset=earliest`.
Per message: broker error → logged (partition EOF ignored), nothing handled or committed · JSON decoded and passed to
`handler(event)` · handler returned → `commit(message, asynchronous=False)` · not JSON, or the handler raised
`ValueError` / `KeyError` → logged as malformed, committed (retrying cannot fix it) · any other exception → logged,
`seek` back to the same offset, wait `backoff` (2 s), redelivered. Handlers must be idempotent. Requires the `kafka`
extra of `libs/common`.

## 6.10 Services

### Public API (gateway)

| Method | Path | Parameters | Forwards to | Responses |
|---|---|---|---|---|
| GET | `/` | — | — | 307 → `/docs` |
| POST | `/api/posts` | JSON body (object) | content `POST /posts` | 201 post · 422 validation · 502 upstream down |
| GET | `/api/posts` | `author` (required, `^[A-Za-z0-9._-]+$`), `limit` 1–50 (20), `before` (id of the last post seen: next page) | content `GET /posts` | 200 `{author, posts[]}` newest first · 422 · 502 |
| GET | `/api/posts/{post_id}` | `post_id: int` | content `GET /posts/{id}` | 200 · 404 · 422 · 502 |
| GET | `/api/search` | `q` 1–200 chars, `author?`, `tag?` (`^[a-z0-9-]{1,32}$`), `limit` 1–50 (10) | search `GET /search` | 200 `{query, hits[]}` · 422 · 502 |
| GET | `/api/notifications` | `author` (required), `limit` 1–50 (20) | notify `GET /outbox` | 200 `{author, notifications[]}` newest first · 422 · 502 |
| GET | `/api/posts/{post_id}/related` | `post_id: int`, `limit` 1–50 (10) | graph `GET /related/{id}` | 200 `{post_id, related[{id, title, author, score, shared_tags, same_author}]}` · 404 · 422 · 502 |
| GET | `/api/tags/{tag}` | `tag` `^[a-z0-9-]{1,32}$`, `limit` 1–50 (10) | graph `GET /tags/{tag}` | 200 `{tag, posts, related[{tag, together}]}` · 404 · 422 · 502 |
| GET | `/api/tags/{tag}/posts` | `tag` `^[a-z0-9-]{1,32}$`, `limit` 1–50 (20) | graph `GET /tags/{tag}/posts` | 200 `{tag, posts[{id, title, author}]}` (newest first) · 404 · 422 · 502 |
| GET | `/api/graph/overview` | `limit` 1–50 (10) | graph `GET /overview` | 200 `{posts, authors, tags, top_tags[{tag, posts}], top_authors[{author, posts}], tag_links[{source, target, together}]}` · 422 · 502 |
| POST | `/api/chat` | `{messages[{role, content}], k}` | chat `POST /chat` (streamed through `common.relay`) | 200 `text/event-stream`: `sources`, `token`…, `done` · 422 · 502 |

### content

`PostIn`: `title` 1–200, `body` 1–20000, `author` 1–64 matching `^[A-Za-z0-9._-]+$`, `tags` 0–5 items each
matching `^[a-z0-9-]{1,32}$` (default `[]`). `Post` = `PostIn` + `id: int`, `created_at: datetime`.
`GET /posts?author=&limit=&before=` returns `{author, posts[]}` ordered `id DESC` (newest first), served by the
index `posts_author_id_idx` (V8); `before=<id>` returns the next page (ids below it). Paging by id keeps the cursor
and the order the same, so no post is skipped between pages; `tools/seed.py` and the portal's loader page this way.

```mermaid
sequenceDiagram
    participant GW as gateway
    participant C as content
    participant PG as PostgreSQL
    participant K as Kafka
    participant S as search indexer
    GW->>C: POST /posts (signed)
    C->>PG: INSERT INTO content.posts … RETURNING id, created_at
    C->>K: produce content.post.created key=id value=Post JSON (acks=all, idempotent)
    C->>C: flush(5 s), not acknowledged → log ERROR, the post stays stored
    C-->>GW: 201 Post
    K-->>S: poll (group "search", earliest, manual commit)
    S->>PG: INSERT … ON CONFLICT (post_id) DO UPDATE
    S->>K: commit offset (after the write)
```

Event `content.post.created` (3 partitions): key = post id, value =
`{"id", "title", "body", "author", "tags", "created_at"}` (`tags` was added later; consumers treat a missing
field as `[]`). Only additive changes; a breaking change needs a new topic. Consumers: `search`, `notify` and `graph`.

### search

- **Indexer**: `EventConsumer` (group `search`) with the handler `index_post` — upsert into `search.documents`,
  missing `tags` → `[]`. At-least-once + upsert = effectively once.
- **Query:** `websearch_to_tsquery('english', q)` against `tsv`; rank `ts_rank_cd`; order `score DESC, post_id
  DESC`; optional `author =` and `tag = ANY (tags)` filters; `LIMIT` 1–50 (default 10). Hits:
  `{id, title, author, tags, score}`.

### notify

- **Consumer**: `EventConsumer` (group `notify`) with the handler `record_notification` — one `notify.outbox` row
  per event, `INSERT … ON CONFLICT (post_id) DO NOTHING`. A replayed event never notifies twice.
- **`GET /outbox?author=&limit=`** (1–50, default 20) → `{author, notifications[{post_id, author, created_at}]}`,
  ordered `created_at DESC, post_id DESC`.

### graph

Neo4j (`bolt://neo4j:7687`, user `neo4j`, password `GRAPH_DB_PASSWORD`); data under `DATA_DIR/neo4j`.

```mermaid
flowchart LR
    A((Author)) -->|WROTE| P((Post))
    P -->|TAGGED| T((Tag))
```

- **Schema**: `db/graph/V1__constraints.cypher` — unique `Post.id`, `Author.name`, `Tag.name`; applied by the
  `graph-init` one-shot (`cypher-shell -f`, `IF NOT EXISTS`) before `graph` starts. Append files, never edit one.
- **Writer**: `EventConsumer` (group `graph`) with the handler `index_post` — one `MERGE` statement for author,
  post (`SET title, created_at`), `WROTE`, and per tag `MERGE (t:Tag)` + `TAGGED`. Idempotent: a redelivered event
  changes nothing. A new consumer group starts at the earliest offset, so the graph rebuilds itself from the topic.
- **`GET /related/{post_id}?limit=`** (1–50, default 10): posts sharing tags (`collect` of shared tag names) and
  posts by the same author; `score = |shared_tags| + (1 if same_author)`; order `score DESC, id DESC`;
  404 when the post is not in the graph (unknown, or not indexed yet).
- **`GET /tags/{tag}?limit=`**: `posts` = posts carrying the tag; `related` = co-occurring tags with
  `together` = posts carrying both, order `together DESC, tag`; 404 for an unknown tag.
- **`GET /tags/{tag}/posts?limit=`** (1–50, default 20): the newest posts carrying the tag, `{id, title, author}`;
  404 for an unknown tag.
- **`GET /overview?limit=`** (1–50, default 10): `posts`, `authors`, `tags` (node counts); `top_tags` and
  `top_authors` by post count; `tag_links` = pairs among the top tags with `together` = posts carrying both
  (`source < target`, order `together DESC`). Feeds the portal's Analyze page and topic map.

### chat

`services/chat/app.py` (endpoint, retrieval, streaming) and `rag.py` (the pipeline's pure steps). `POST /chat`
`{messages: [{role: user|assistant, content ≤ 4000}] (1–20, last = user), k: 1–10 (5)}` → `text/event-stream`.

```mermaid
flowchart LR
    q[question] --> kw[keywords<br/>stopwords out; a short follow-up<br/>borrows the previous question's]
    kw -->|"w1 or w2 or …"| s[search<br/>top k]
    s -->|3 best hits| g[graph /related<br/>≤ 2 each, ≤ 3 total]
    s & g --> c[content<br/>full text]
    c --> p[prompt: rules + numbered posts<br/>+ last 8 turns]
    p --> m[model · common.llm<br/>OpenAI-compatible, streamed]
    m --> f[ThinkFilter<br/>drops &lt;think&gt;] --> out[token events<br/>done: citations]
```

| Event | Data |
|---|---|
| `sources` (first, once) | `[{id, title, author, tags, via: search\|graph, near?, snippet}]` — what the model was given |
| `token` | `{text}` — the answer, piece by piece |
| `done` (last) | `{citations: [ids cited as [#id] that are sources], model: name\|null}` |
| `error` | `{detail}` — the model failed after it had started answering |

Retrieval errors are HTTP errors before the stream starts (502). Without a model (`CHAT_LLM_URL` empty, unreachable,
or an error status) the answer lists the retrieved posts, cited, and `model` is `null`; with no matching post it
says so. The model client (`libs/common/common/llm.py`) is the only place that calls a model: semgrep's
`unsigned-service-call` keeps raw HTTP out of `services/`. Gateway and web pass the stream through with
`common.relay` (chunks forwarded as they arrive, read timeout 180 s). Contract: `contract/test_chat.py` holds with
and without a model.

### web (rag-web)

The portal: a FastAPI app (`services/web/app.py`) that serves a dependency-free browser client
(`services/web/static/`: `index.html`, `app.js` — router and pages, `graph.js` — force-directed SVG graph,
`style.css`, `datasets/` — sample data: `index.json`, `general.json`, `bank.json`) and forwards `GET`/`POST /api/{path}` to the gateway with `SignedClient`
(signed as `web`; the gateway API is public, so it trusts no list). Same origin for page and API: no CORS.
Body limit 64 KiB (413), `..` segments rejected (404), other methods 405, gateway down → 502; status and body
of the gateway pass through unchanged. Host port `WEB_PORT` (8081).

| Page | Route | Calls |
|---|---|---|
| Analyze | `#/` | `/api/graph/overview` — counts, top tags/authors, topic map (tag co-occurrence graph), strongest pairs; loads a sample dataset (`datasets/index.json`) through the API, skipping posts already there |
| Search | `#/search?q=&tag=&author=` | `/api/search` — results with highlights, tag and author facets to narrow |
| Write | `#/write` | `POST /api/posts`, then polls search, `/related` and `/api/notifications` to show each consumer catching up |
| Post | `#/post/{id}` | `/api/posts/{id}`, `/related` — body, related posts with score, neighbourhood graph |
| Tag | `#/tag/{tag}` | `/api/tags/{tag}`, `/api/tags/{tag}/posts` — co-occurring tags, newest posts, authors |
| Author | `#/author/{name}` | `/api/posts?author=`, `/api/notifications` — posts, topics, notifications, author map |
| Graph explorer | `#/graph?tag=\|post=\|author=` | click a node to expand it (tag → posts + co-tags, post → author + tags + related, author → posts + tags) |
| Chat | `#/chat` | `POST /api/chat` (streamed) — thread with live answer, `[#id]` citations as links, sources panel with a graph of the sources, Stop, New chat; the conversation is kept for the browser session |

### Sample data (`tools/seed.py`, `services/web/static/datasets/`)

| Dataset | Posts | Authors | Tags | Content |
|---|---|---|---|---|
| `general` | 24 | 6 | 15 | RAG, Kafka, knowledge graphs, Postgres, security, observability |
| `ardshinbank` | 46 | 7 | 28 | Ardshinbank (Armenia), summarised from its public website with a source URL per post: history and network, debit, credit and premium cards, ArCa, Google/Apple Pay, consumer and mortgage loans, refinancing, deposits and savings, mobile app and transfers (UBPay), SME and corporate banking, POS acquiring, STATUS premium banking. No rates or fees: they change, the posts point to the bank's terms |
| `bank` | 100 | 10 | 35 | loans, credit risk (PD, LGD, EAD, provisioning), mortgages, cards and credit scores, debit and accounts, payments, fraud, compliance (KYC, AML, sanctions), treasury (rates, liquidity, capital), financial education |

`./app.sh seed <dataset|path.json>` / `make seed d=<dataset>` runs the `seed` container (tools profile): it validates
the file with the rules of `POST /api/posts`, lists each author's existing posts, posts only the missing ones
(idempotent) and waits until the last one is in the graph. The portal's loader does the same in the browser.
`index.json` lists the datasets with a `marker` tag and suggested `questions`; Chat offers the questions of the
datasets whose marker tag is in the graph. CI seeds `bank` twice (100, then 0 created) and checks that Chat
retrieves the right banking post.

## 6.11 Database (`db/migrations`)

| Migration | Content |
|---|---|
| `V1__service_roles.sql` | roles `content_svc`, `search_svc` (`LOGIN`, password from Flyway placeholders `${content_db_password}`, `${search_db_password}`); `REVOKE CREATE ON SCHEMA public FROM PUBLIC` |
| `V2__content_posts.sql` | schema `content`; `content.posts` |
| `V3__search_documents.sql` | schema `search`; `search.documents` + indexes |
| `V4__content_posts_author_idx.sql` | index `(author, created_at DESC, id DESC)` for listing by author |
| `V5__content_posts_tags.sql` | `content.posts.tags text[] NOT NULL DEFAULT '{}'`, at most 5 |
| `V6__search_documents_tags.sql` | `search.documents.tags` + GIN index |
| `V7__notify_outbox.sql` | role `notify_svc` (placeholder `${notify_db_password}`); schema `notify`; `notify.outbox` + index |
| `V8__content_posts_author_id_idx.sql` | index `(author, id DESC)` for paging an author's posts with `before` |

```mermaid
erDiagram
    CONTENT_POSTS {
        bigint id PK "GENERATED ALWAYS AS IDENTITY"
        text title "CHECK length 1..200"
        text body
        text author "btree (author, created_at DESC, id DESC)"
        text[] tags "DEFAULT {}, at most 5"
        timestamptz created_at "DEFAULT now()"
    }
    SEARCH_DOCUMENTS {
        bigint post_id PK "= content.posts.id (via event, no FK)"
        text title
        text body
        text author "btree index"
        tsvector tsv "GENERATED: title weight A, body weight B; GIN index"
        text[] tags "GIN index"
    }
    NOTIFY_OUTBOX {
        bigint post_id PK "= content.posts.id (via event, no FK)"
        text author "btree (author, created_at DESC, post_id DESC)"
        timestamptz created_at
        timestamptz recorded_at "DEFAULT now()"
    }
    CONTENT_POSTS ||..o| SEARCH_DOCUMENTS : "content.post.created"
    CONTENT_POSTS ||..o| NOTIFY_OUTBOX : "content.post.created"
```

Grants: `content_svc` → `USAGE` on `content`, `SELECT, INSERT` on `content.posts`. `search_svc` → `USAGE` on
`search`, `SELECT, INSERT, UPDATE` on `search.documents`. `notify_svc` → `USAGE` on `notify`, `SELECT, INSERT` on
`notify.outbox`. Objects are owned by the migration user (`postgres`).
The `migrate` one-shot runs Flyway with `FLYWAY_CONNECT_RETRIES=30`; the placeholders come from
`CONTENT_DB_PASSWORD` / `SEARCH_DB_PASSWORD` / `NOTIFY_DB_PASSWORD`, the same variables used in each service's
`DB_DSN`.

## 6.12 Eval (`eval/run_eval.py`)

1. Load `corpus.yaml` (`version`, `docs[key,title,body]`, `queries[q, relevant[]]`).
2. Author `eval-<version>`; if the corpus is not yet indexed, create every doc through `POST /api/posts`; wait up
   to 60 s until all titles are found (indexing is asynchronous).
3. Per query: `GET /api/search?q=…&author=…&limit=10`; map hit ids to doc keys.
   - recall@5 = |relevant ∩ top-5| / |relevant|
   - RR = 1 / rank of the first relevant hit (0 if none); MRR@10 = mean RR
   - judge (optional, `JUDGE_BASE_URL`): the top hit graded 0–3 with `harness/prompts/judge.md`;
     judge@1 = Σ grades / (3 · judged)
4. Regression = recall@5 or MRR@10 < baseline − `EVAL_TOLERANCE` (0.05) → exit 1 (the sensor is blocking).
   A judge@1 drop is printed and marked `drop (advisory)`; it never fails the run.
5. `EVAL_BASELINE` (default `eval/baseline.json`) lets the harness selftest judge the search against seeded
   baselines in `harness/sensors/fixtures/eval/`.
6. Writes `$EVAL_OUT/eval-results.json` (promote to `eval/baseline.json` deliberately) and `eval-report.md`.

## 6.13 `run.sh`

```mermaid
flowchart TD
    A[parse options] --> B{mode}
    B -->|"--down"| D["make down"] --> Z["exit 0"]
    B -->|"--urls"| U["docker compose ps, URLs, next steps"] --> Z
    B -->|up| P["preflight: docker, daemon, compose,<br/>make, .env, free ports, mkdir .harness"]
    P --> S["make up-observability or make up<br/>waits for healthchecks"]
    S --> T["smoke test: POST, GET, search within 20 s"]
    T --> L{"--llm ?"} -->|yes| LL["make llm"]
    L --> K{"--check or --full ?"}
    K -->|yes| H["selftest, harness-fast, harness-integration<br/>plus harness-pipeline with --full"]
    K --> O["print URLs and next steps"]
    H --> O
    O --> X["exit 0 if every step passed, else 1"]
```

URL values come from the environment, then `.env`, then defaults (`PUBLIC_HOST`, `GATEWAY_PORT`,
`PROMETHEUS_PORT`, `OLLAMA_PORT`). Only running services are listed as reachable.

## 6.14 CI (`.github/workflows/harness.yml`)

Triggers: pull requests, pushes to `main`, nightly (03:17 UTC), manual. One job on `ubuntu-latest`:
checkout (full history) → setup-python 3.12 + PyYAML, `DATA_DIR=$RUNNER_TEMP/air-harness-data` →
`make harness-build` → `make harness-test`, `harness-coverage`, `harness-selftest` → `make harness-static` →
nightly: `make harness-selftest-live`, `make harness-continuous`; otherwise `./run.sh --full` → report and eval report into the job summary →
service logs on failure → `.harness/` as an artifact → `make clean`. `MIGRATIONS_BASE` is
`origin/<base branch>` on pull requests and `HEAD~1` on pushes.

## 6.15 Configuration reference

All variables have defaults in `docker-compose.yml` / `compose.harness.yml` and are listed in `.env.example`
(topology T8 enforces it). Main ones:

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/var/tmp/air-harness` | persistent data (postgres, kafka, neo4j, ollama) |
| `GATEWAY_PORT` / `WEB_PORT` / `PROMETHEUS_PORT` / `OLLAMA_PORT` | 8080 / 8081 / 9090 / 11434 | host ports |
| `POSTGRES_DB`, `POSTGRES_PASSWORD` | `air_harness`, `postgres-dev` | database |
| `CONTENT_DB_PASSWORD`, `SEARCH_DB_PASSWORD`, `NOTIFY_DB_PASSWORD` | `content-dev`, `search-dev`, `notify-dev` | service roles |
| `GRAPH_DB_PASSWORD`, `NEO4J_HEAP` | `graph-dev`, `512m` | Neo4j graph store |
| `CHAT_LLM_URL`, `CHAT_MODEL`, `CHAT_LLM_API_KEY` | `http://ollama:11434/v1`, `qwen3:8b`, `not-needed` | Chat model (any OpenAI-compatible endpoint; set the URL empty for sources-only answers) |
| `LOG_LEVEL` | `INFO` | services |
| `KAFKA_HEAP_OPTS` | `-Xmx512m -Xms256m` | broker heap |
| `*_TAG` | pinned | image versions |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `REVIEW_MODEL`, `LLM_NO_THINK` | empty (review skipped), `qwen3:8b` | review agent (opt-in) |
| `REVIEW_DIFF_BASE` | empty | what the reviewer reviews |
| `EVAL_TOLERANCE`, `JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_API_KEY` | 0.05, empty | eval |
| `HARNESS_IMAGE`, `HARNESS_TIMEOUT`, `MIGRATIONS_BASE` | runner 0.5.1, 300, `HEAD` | harness |
| `PUBLIC_HOST` | `localhost` | host name printed by `run.sh` |

Next: [Demo](07-demo.md) · back to the [documentation index](../README.md).
