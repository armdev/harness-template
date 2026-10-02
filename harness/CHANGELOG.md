# Changelog — harness template `py-services-pg-kafka`

## 0.2.0

Product name: **air-harness** (was haytarar). Images `air-harness/*`, runner image `air-harness-runner`,
compose project `air-harness`, database `air_harness`, default `DATA_DIR=/var/tmp/air-harness`.

- `run.sh`: one command to run the product — preflight, build + start, smoke test through the public API,
  optional harness stages (`--check`, `--full`), local LLM (`--llm`), then every accessible URL and next steps.
  `--urls` and `--down` for a running stack. CI runs `./run.sh --full`.
- `help.sh`: the guide in the terminal (run, commands, urls, harness, agent, prompts, config, troubleshoot) and
  `help.sh prompt <n>` to print a prompt ready to paste or pipe into an agent.
- Next-step prompts `harness/prompts/next-steps/01..08`: explore, first endpoint, schema change, new service,
  fix RED, review, ship, improve the harness.
- Gateway: `/` redirects to the API docs; documented request body with an example.

First version that runs end to end: `make up` starts a reference system and every sensor has something real
to observe.

- Layout: runner, sensors, rules, rubric and skills under `harness/` as documented (were flat at the root).
- Reference system: gateway / content / search, Ed25519 signed calls (`libs/common`), PostgreSQL with a role
  and schema per service, Flyway, Kafka (KRaft) with `kafka-init`, Prometheus alerts, contract suite, search eval.
- Runner: `list` verb; `run --only` validates the id and plane (exit 2/3); stale results are marked in the
  report; `WARN` lines of passing sensors are reported; blind blocking sensors turn the verdict RED;
  selftest checks clean fixtures stay quiet (`# expect: clean`) and accepts directory fixtures (`.expect`);
  coverage validates every stage, plane, kind and fixture path.
- New sensors: `migrations` (M1–M5), `unit`. Topology gains T7 alerts-present, T8 env-documented,
  T9 data-outside-repo, a caller-key check under T2, `--strict`, and skips dev-profile tooling in T1.
  Semgrep gains `unsigned-service-call`. Seeded defects for topology, migrations, ruff, semgrep, vulture.
- Review agent: prompt in `harness/prompts/review.md`; reviews unstaged + untracked work when nothing is staged;
  tolerant JSON parsing.
- Guides: skills `new-endpoint`, `db-migration`, `new-topic`, `harness-report`, `harness-steer`; rubric R4
  (schema ownership), R8 (consumers), R9 (eval); agent prompt templates; Claude Code Stop hook; git pre-commit.
- Removed: Java parity sensor (no Java implementation ships; see "Extending to a second implementation").

Expected first-run impact on existing projects: T7 and T8 fire until `x-harness` paths exist and are complete;
`migrations` M4 fires on tables created without a grant in the same file.

## 0.1.0

Skeleton: manifest, runner, topology and review sensors, rubric, new-service skill.
