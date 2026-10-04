-- planner: its own role and schema. Password from the Flyway placeholder fed by PLANNER_DB_PASSWORD (compose),
-- the same variable the service uses in its DB_DSN.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'planner_svc') THEN
    CREATE ROLE planner_svc LOGIN PASSWORD '${planner_db_password}';
  END IF;
END
$$;

CREATE SCHEMA planner;
GRANT USAGE ON SCHEMA planner TO planner_svc;

-- People whose work is planned. capacity_hours: focus hours a day for tasks (meetings come on top, within 09-18).
CREATE TABLE planner.employees (
    handle          text         PRIMARY KEY,
    name            text         NOT NULL,
    role            text         NOT NULL,
    team            text         NOT NULL,
    capacity_hours  numeric(3,1) NOT NULL CHECK (capacity_hours > 0 AND capacity_hours <= 10),
    updated_at      timestamptz  NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON planner.employees TO planner_svc;

-- Jira-style tasks. depends_on: keys of tasks that must be done first (they may belong to someone else).
CREATE TABLE planner.tasks (
    key             text         PRIMARY KEY,
    title           text         NOT NULL,
    description     text         NOT NULL DEFAULT '',
    severity        text         NOT NULL CHECK (severity IN ('blocker', 'critical', 'major', 'minor', 'trivial')),
    status          text         NOT NULL CHECK (status IN ('todo', 'in_progress', 'review', 'done')),
    assignee        text         REFERENCES planner.employees (handle),
    estimate_hours  numeric(5,2) NOT NULL CHECK (estimate_hours > 0),
    due             date,
    depends_on      text[]       NOT NULL DEFAULT '{}',
    updated_at      timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX tasks_assignee_idx ON planner.tasks (assignee);
GRANT SELECT, INSERT, UPDATE ON planner.tasks TO planner_svc;

-- Outlook-style meetings, on the office's wall clock (no time zone: the working day is 09:00-18:00 local).
CREATE TABLE planner.meetings (
    id              text         PRIMARY KEY,
    title           text         NOT NULL,
    starts_at       timestamp    NOT NULL,
    ends_at         timestamp    NOT NULL,
    organizer       text         NOT NULL,
    attendees       text[]       NOT NULL,
    CHECK (ends_at > starts_at)
);
CREATE INDEX meetings_attendees_idx ON planner.meetings USING gin (attendees);
CREATE INDEX meetings_starts_idx ON planner.meetings (starts_at);
GRANT SELECT, INSERT, UPDATE ON planner.meetings TO planner_svc;
