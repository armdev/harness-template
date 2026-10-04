# 4. Implemented architecture

air-harness has two halves that live in one repository:

1. **The harness** — guides and sensors that regulate a coding agent.
2. **The reference system** — the application the harness regulates (gateway, content, search, notify on PostgreSQL, graph on Neo4j
   and Kafka). It exists so every sensor has real code to observe; in your own project it is replaced by your
   services.

## 4.1 System context

```mermaid
flowchart TB
    dev([Developer]) -->|tasks, prompts| agent([Coding agent<br/>Claude Code, Codex, ...])
    dev -->|./run.sh, ./help.sh, make| repo
    agent -->|reads guides| guides[Guides<br/>AGENTS.md · skills · rubric · prompts]
    agent -->|edits| repo[(Repository)]
    repo --> sensors[Sensors<br/>harness containers + host]
    sensors -->|.harness/report.md| agent
    sensors -->|ledger.jsonl| steer[Steering loop<br/>stats · coverage · selftest]
    steer -->|strengthen| guides
    sensors -.->|review / judge| llm[(OpenAI-compatible LLM<br/>optional)]
    ci([GitHub Actions]) -->|./run.sh --full| sensors
    repo --> stack[Reference system<br/>docker compose]
    sensors -->|contract, eval| stack
```

## 4.2 Harness architecture

### Planes — where a sensor runs

```mermaid
flowchart LR
    subgraph host[Host / CI runner]
        make[make · run.sh] --> runner_h[harness.py<br/>plane=host]
        runner_h -->|make test / contract / eval<br/>docker run promtool| compose_tools[tools containers]
    end
    subgraph static[Container 'harness' · network_mode: none · read-only repo · cap_drop ALL]
        runner_s[harness.py<br/>plane=static] --> s1[topology] & s2[migrations] & s3[ruff] & s4[semgrep] & s5[vulture]
    end
    subgraph live[Container 'harness-live' · project network]
        runner_l[harness.py<br/>plane=live] --> r1[review agent] & r2[pip-audit]
    end
    make --> static
    make --> live
    r1 -.-> llm[(LLM)]
    static & live & runner_h --> out[(.harness/<br/>results · report.md · ledger.jsonl)]
```

- **static** — hermetic and fast: no network, the repository mounted read-only, no Linux capabilities, a
  read-only root filesystem. The agent's code cannot phone home; sensors observe, they never edit.
- **live** — same image, on the project network: reaches the LLM and the running stack.
- **host** — the developer machine or CI runner, through `make` and `docker compose` (contract suite, eval,
  promtool).

All three planes write into one output directory; the runner merges the latest result of every sensor of the
stage into one report.

### Stages — when a sensor runs (keep quality left)

| Stage | Trigger | Sensors |
|---|---|---|
| pre-commit | every change (agent loop, git hook, Stop hook) | topology, migrations, ruff, semgrep-local · review-agent (advisory) |
| integration | before "done", stack up | unit, contract |
| pipeline | CI on every PR / push | static sensors + unit, contract, eval, prom-rules |
| continuous | nightly | dead-code, deps-audit (advisory) |

### The manifest is the architecture of the harness

`harness.yaml` declares 12 guides and 11 sensors. Each sensor has `kind`, `category`, `plane`, `stages`,
`blocking`, `run`, `pairs_with` (the guides that teach its rule), `fix_hint` and optionally `selftest`
(fixtures + command). The runner, the coverage matrix, the report and the steering statistics are all derived
from it.

### Feedback loops

```mermaid
flowchart LR
    subgraph inner[Inner loop · seconds to minutes · the agent]
        e[edit] --> f[harness-fast] --> r[report] --> e
    end
    subgraph outer[Outer loop · days to weeks · maintainers]
        l[ledger] --> st[harness-stats] --> g[strengthen guide /<br/>add computational rule] --> sf[selftest + coverage]
    end
    r -. every run appended .-> l
    sf -. new rule .-> f
```

## 4.3 Reference system architecture

### Containers and call graph

```mermaid
flowchart LR
    browser([Browser]) -->|HTTP :8081| web[web · rag-web<br/>portal]
    web -->|signed Ed25519 · /api/*| gw
    client([Client / contract tests / eval]) -->|HTTP :8080| gw[gateway<br/>public API]
    gw -->|signed Ed25519| content[content<br/>owns posts]
    gw -->|signed Ed25519| search[search<br/>full-text index]
    gw -->|signed Ed25519| notify[notify<br/>notification outbox]
    gw -->|signed Ed25519| kg[graph<br/>knowledge graph]
    gw -->|signed · streamed| chat[chat<br/>RAG answers]
    chat -->|retrieve| search & kg & content
    chat -.->|OpenAI-compatible| llm[(LLM<br/>Ollama or hosted)]
    content -->|content.post.created| kafka[(Kafka<br/>KRaft)]
    kafka -->|consumer group 'search'| search
    kafka -->|consumer group 'notify'| notify
    kafka -->|consumer group 'graph'| kg
    content -->|content_svc · schema content| pg[(PostgreSQL)]
    search -->|search_svc · schema search| pg
    notify -->|notify_svc · schema notify| pg
    kg -->|bolt · Author-WROTE-Post-TAGGED-Tag| neo[(Neo4j)]
    prom[Prometheus] -.->|scrape /metrics| web & gw & content & search & notify & kg & chat
```

| Service | Responsibility | Exposed | Data | Trusts |
|---|---|---|---|---|
| web | rag-web portal: serves the browser client (analyze, search, graph explorer, write) and forwards its `/api/*` calls to the gateway | host `:8081` | — | (public) |
| gateway | public HTTP API; validates and forwards; holds no data | host `:8080` | — | (public) |
| content | creates, reads and lists posts (with tags); publishes `content.post.created` | internal `:8000` | `content.posts` (role `content_svc`) | gateway, chat |
| search | indexes events; full-text search with author and tag filters | internal `:8000` | `search.documents` (role `search_svc`) | gateway, chat |
| notify | records one notification per new post (stand-in for e-mail); lists them | internal `:8000` | `notify.outbox` (role `notify_svc`) | gateway |
| graph | knowledge graph of authors, posts and tags; related posts, tag neighbourhoods, tagged posts, overview | internal `:8000` | Neo4j (`Author`, `Post`, `Tag`; schema in `db/graph`) | gateway, chat |
| chat | answers questions: search → graph → content → model, citing `[#id]`, streamed (SSE); sources only without a model | internal `:8000` | — (calls a model at `CHAT_LLM_URL`) | gateway |

### Cross-cutting decisions

| Concern | Decision | Enforced by |
|---|---|---|
| Service identity | one Ed25519 key per service, generated by the `service-keys` one-shot; each service mounts only its own private key, and every callee the public keys | topology T2, T10 |
| Authorization | callee accepts only callers in its `TRUSTED_CALLERS`; unsigned → 401, untrusted → 403 | topology T1, semgrep `unsigned-service-call`, contract `test_service_auth`, rubric R1 |
| Data ownership | each service has its own role and schema; no cross-schema reads | migrations M4, rubric R4 |
| Schema changes | Flyway only, append-only history; Neo4j constraints in `db/graph/*.cypher` via `graph-init`; services own no DDL | migrations M1–M5, semgrep `ddl-outside-migrations` (SQL and Cypher) |
| Events | topics created by `kafka-init`, auto-create off; idempotent consumer, commit after write | topology T5, semgrep `kafka-consumer-auto-commit`, rubric R8 |
| Configuration | `${NAME:-default}` in compose + `.env.example` | topology T3, T8, rubric R5 |
| Persistence | under `DATA_DIR`, never in the repository | topology T9 |
| Observability | JSON logs with request id; `http_requests_total`, `http_request_duration_seconds`; alerts per service | topology T7, prom-rules |
| Supply chain | pinned image tags and package versions | topology T6, deps-audit |
| Behaviour | the contract suite is the specification | contract, rubric R2 |

### Deployment and startup order (docker compose)

```mermaid
flowchart TB
    si[storage-init<br/>one-shot] --> pg[(postgres)] & kf[(kafka)] & neo[(neo4j)]
    neo -->|healthy| gi[graph-init · Cypher<br/>one-shot]
    pg -->|healthy| mig[migrate · Flyway<br/>one-shot]
    kf -->|healthy| ki[kafka-init<br/>one-shot]
    sk[service-keys<br/>one-shot]
    sk & mig & ki -->|completed| content & search & notify
    sk --> gw[gateway]
    sk & gi & ki -->|completed| kg
    content & search & kg -->|healthy| chat[chat]
    content & search & notify & kg & chat -->|healthy| gw
    gw -->|healthy| web[web]
```

Optional profiles: `observability` (Prometheus), `local-llm` (Ollama), `tools` (contract, unit, eval
containers). One-shots exit 0 and the dependents wait on `service_completed_successfully`.

### Security posture of the containers

Application services run as uid 10001 with `read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]` and
`no-new-privileges`; only the gateway publishes a port. Sensor containers additionally run with the
invoking user's uid so reports are owned by the developer.

Next: [Components](05-components.md)
