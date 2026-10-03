-- notify: its own role and schema. Password from the Flyway placeholder fed by NOTIFY_DB_PASSWORD (compose),
-- the same variable the service uses in its DB_DSN.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'notify_svc') THEN
    CREATE ROLE notify_svc LOGIN PASSWORD '${notify_db_password}';
  END IF;
END
$$;

CREATE SCHEMA notify;
GRANT USAGE ON SCHEMA notify TO notify_svc;

-- One row per post (a stand-in for sending an e-mail). post_id is the idempotency key: a redelivered event
-- does not notify twice.
CREATE TABLE notify.outbox (
    post_id      bigint      PRIMARY KEY,
    author       text        NOT NULL,
    created_at   timestamptz NOT NULL,
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outbox_author_created_idx ON notify.outbox (author, created_at DESC, post_id DESC);

GRANT SELECT, INSERT ON notify.outbox TO notify_svc;
