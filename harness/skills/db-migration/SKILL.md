---
name: db-migration
description: Change the haytarar database schema with a Flyway migration (new table, column, index, role or grant). Use whenever a task needs DDL or a new database role.
---

# Change the schema

Schema lives only in `db/migrations` and is applied by the `migrate` one-shot (Flyway) as the migration user.
Services connect as `<name>_svc` roles that own nothing and cannot run DDL (semgrep `ddl-outside-migrations`).

1. **New file, never an edit.** Next free number: `ls db/migrations`. Name `V<n>__<snake_case>.sql`
   (`R__<name>.sql` only for repeatable objects such as views). A committed `V` file has already run somewhere;
   editing it is caught by the migrations sensor (M3) — put the change in a new file.
2. **Each service its own schema.** Tables go into the schema of the service that owns them
   (`content.*`, `search.*`). Another service needs the data → it gets it through the owner's API or events
   (rubric R4), not through a grant on someone else's table.
3. **Grant in the same file.** Every `CREATE TABLE` is followed by the least `GRANT` the owning role needs
   (`SELECT, INSERT` — add `UPDATE`/`DELETE` only when the code does it). Sensor rule M4.
4. **Backward compatible.** The old version of the service keeps running while the migration applies: add
   nullable columns or columns with defaults, backfill in a later migration, drop in a later release.
5. **New role** (new service): add it to a new migration with the `DO $$ ... IF NOT EXISTS ... $$` pattern of
   `V1__service_roles.sql`, password from a placeholder `${<name>_db_password}`; then in `docker-compose.yml`
   add `FLYWAY_PLACEHOLDERS_<NAME>_DB_PASSWORD: ${<NAME>_DB_PASSWORD:-<name>-dev}` to `migrate`, the same
   variable in the service's `DB_DSN`, and `<NAME>_DB_PASSWORD` to `.env.example`.
6. **Verify**: `make harness-fast` (migrations sensor), then `make up` — `migrate` exits 0 — and `make contract`.

Inspect the live schema: `docker compose exec postgres psql -U postgres -d haytarar -c '\dt content.*'`.
