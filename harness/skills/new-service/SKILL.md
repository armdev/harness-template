---
name: new-service
description: Add a new backend service to air-harness (compose entry, identity, DB role, migrations, contract, alerts). Use whenever a task needs a new deployable, or a new caller -> callee edge between services.
---

# Add a service

Work through these in order; `make harness-fast` must be green at the end (topology, migrations, semgrep).
Use `services/content` as the reference for a service with a database and events, `services/gateway` for one
that only calls others.

1. **Code**: `services/<name>/` with `app.py`, `requirements.txt` (pinned) and a `Dockerfile` copied from an
   existing service (build context is the repo root so it can install `libs/common`). Build the app with
   `common.telemetry.create_app("<name>", lifespan=...)`: that gives logging, `/healthz`, `/metrics`.
2. **Compose entry**: copy the closest existing service. Use `<<: [*py, *internal]`, `environment: { <<: *py-env, ... }`
   and `SERVICE_NAME: <name>`. If you write an explicit `depends_on`, it *replaces* the anchor's: repeat
   `service-keys` (and `migrate`, `kafka-init` when used).
3. **Identity**: append `<name>` to the `service-keys` entrypoint list; mount the `service-keys` volume twice,
   `subpath: <name>` at `/run/keys/self` and `subpath: public` at `/run/keys/public` (both `read_only`).
4. **Who may call it**: `TRUSTED_CALLERS` on the new service; add the new service to the `TRUSTED_CALLERS`
   of every service it calls. Declare each call as `<CALLEE>_URL: http://<callee>:8000` so the call graph stays
   declarative (topology T1/T2 read it), and call through `common.service_auth.SignedClient(os.environ["<CALLEE>_URL"])`.
   Protect every endpoint with `Depends(require_caller())`.
5. **Database** (if it stores data): follow `harness/skills/db-migration/SKILL.md` — role `<name>_svc` created in a
   migration with a `${<name>_db_password}` placeholder, `FLYWAY_PLACEHOLDERS_<NAME>_DB_PASSWORD` on `migrate`,
   the same `${<NAME>_DB_PASSWORD:-<name>-dev}` in the service's `DB_DSN`, the variable in `.env.example`.
6. **Events** (if it produces or consumes): follow `harness/skills/new-topic/SKILL.md`; depend on `kafka-init`.
7. **Behaviour**: contract tests in `contract/` for every endpoint the gateway exposes for it
   (`harness/skills/new-endpoint/SKILL.md`).
8. **Operations**: a scrape job in `infra/prometheus/prometheus.yml` and up / error-rate / latency rules for
   `job="<name>"` in `infra/prometheus/alerts.yml` (topology T7).
9. **Verify**: `make harness-fast`, then `make up && make harness-integration`.

Checklist the topology sensor enforces: T1 (trusted caller), T2 (key provisioned and mounted), T3 (one default
per variable), T4 (waits for migrate), T5 (waits for kafka-init), T6 (pinned images), T7 (alerts), T8 (variable
in `.env.example`), T9 (no writable bind mount into the repo).
