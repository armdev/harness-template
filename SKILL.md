---
name: new-service
description: Add a new backend service to haytarar (compose entry, identity, DB role, migrations, contract, alerts). Use whenever a task needs a new deployable.
---

# Add a service

Work through these in order; `make harness-fast` must be green at the end (topology sensor).

1. **Code**: `services/<name>/` with its own `Dockerfile`; reuse `libs/common` for auth, logging, telemetry.
2. **Compose entry**: copy the closest existing service. Use `<<: *py` and `<<: *internal`.
   If you write an explicit `depends_on`, it *replaces* the anchor's: repeat `migrate` and `service-keys`.
3. **Identity**: append `<name>` to the `service-keys` entrypoint list; mount `subpath: <name>` and `subpath: public`.
4. **Who may call it**: `TRUSTED_CALLERS` on the new service; add the new service to the `TRUSTED_CALLERS`
   of every service it calls. Use `<CALLEE>_URL: http://<callee>:8000` so the call graph stays declarative.
5. **Database**: role `<name>_svc` with a password variable in `postgres` and `migrate`; tables via Flyway in `db/migrations`.
6. **Events**: topics via `kafka-init`; depend on `kafka-init` if you consume or produce.
7. **Behaviour**: contract tests in `contract/` for every endpoint other services or the web use.
8. **Operations**: Prometheus alert rules for up / error rate / latency; a Grafana panel.
