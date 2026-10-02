-- One login role per service (<name>_svc). Passwords are Flyway placeholders fed from compose
-- (FLYWAY_PLACEHOLDERS_<NAME>_DB_PASSWORD), so the same variable reaches migrate and the service's DB_DSN.
-- Roles own nothing: the migration user owns every object and grants only what each service needs.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'content_svc') THEN
    CREATE ROLE content_svc LOGIN PASSWORD '${content_db_password}';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'search_svc') THEN
    CREATE ROLE search_svc LOGIN PASSWORD '${search_db_password}';
  END IF;
END
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
