# Changelog — harness template `py-services-pg-kafka`

## 0.3.6

- **Seeded defects for `contract`**, the last blocking sensor without them. `mutate.py` takes `target: gateway`:
  it runs a second gateway from a mutated copy of `services/gateway` next to the stack (`docker compose run
  --no-deps`, no host port) and points the contract suite at it. `harness/sensors/fixtures/contract/`: the author
  filter dropped from `GET /api/posts` (`test_list_by_author_only_returns_that_author`), the tag filter dropped
  from search (`test_search_filters_by_tag`), every upstream status turned into 200 (`test_unknown_post_is_404`),
  and an unmodified gateway that must pass the whole contract. Removing the gateway's `limit` validation was
  considered and rejected as a mutant: search validates `limit` too, so the contract rightly still passes.
- Every blocking sensor now has seeded defects; `selftest` reports `firing ability unproven` only for the
  advisory review agent (needs an LLM).
- First-run impact on existing projects: none; `make harness-selftest-host` takes about a minute longer.

## 0.3.5

- **Seeded defects for `unit`, as mutants.** `harness/sensors/mutate.py` applies one mutant to a copy of
  `libs/common` and runs the unit tests on it; `harness/sensors/fixtures/unit/` holds four, each naming the test
  that must turn red: signatures not verified (`test_tampered_body_fails`), `TRUSTED_CALLERS` ignored
  (`test_untrusted_caller_is_forbidden`), clock skew ignored (`test_stale_timestamp_fails`), the Kafka offset
  committed after a failed handler (`test_handler_failure_seeks_back_and_retries_without_committing`), plus an
  identity mutant that must stay quiet. A mutant whose `find` text no longer occurs exactly once exits 126, so a
  stale fixture is reported BLIND, never as a pass. Taught in `harness/skills/harness-steer/SKILL.md` step 3.
- First-run impact on existing projects: none; projects that change `libs/common` may need to refresh a mutant's
  `find` text (the selftest says which).

## 0.3.4

- **Seeded defects for `eval`**, blocking since 0.3.1 but unproven: `harness/sensors/fixtures/eval/` holds
  baselines the current search is judged against — one it misses by more than the tolerance must fire
  (`regression in recall@5`), one inside the tolerance and the agreed numbers must stay quiet. `run_eval.py` reads
  `EVAL_BASELINE` (default `eval/baseline.json`); the selftest mounts each fixture and writes to the container's
  `/tmp`, so `.harness/eval-report.md` is untouched.
- `make harness-selftest-host` now needs the stack up (eval). CI no longer runs it before the stack starts;
  `./run.sh --check` / `--full` run it after the stack is healthy.
- First-run impact on existing projects: none.

## 0.3.3

- **Seeded defects for `prom-rules`** (blocking, host plane), which had none: `harness/sensors/fixtures/prom-rules/`
  — an unparsable PromQL expression and a duration written in words must fire, a minimal valid rule file must stay
  quiet. New `make harness-selftest-host`, run in CI on every PR and by `./run.sh --check`.
- **Runner fixes found by it.** `selftest` substituted `{fixture}` with `str.format`, so a selftest command using a
  shell default such as `${PROMETHEUS_TAG:-v3.6.0}` crashed the runner (KeyError); it now replaces only `{fixture}`.
  The pointer printed for static sensors outside the static plane named a target that does not exist; it now says
  `make harness-selftest`.
- First-run impact on existing projects: none on product code; projects with their own selftest commands that
  escape braces as `{{ }}` for `str.format` must unescape them.

## 0.3.2

- **`deps-audit` was blind and reported it as findings — fixed.** Seeding the sensor (it had no selftest) showed
  that pip-audit could never run in `harness-live`: it builds a throwaway venv under `/tmp`, and the container's
  tmpfs is `noexec`. pip-audit exits 1 for that too, so every nightly run showed a FAIL with environment errors
  instead of an audit. `harness-live` now mounts `/tmp` with `exec` (the hermetic `harness` container keeps
  `noexec`), and the sensor is `harness/sensors/deps_audit.py`, which exits 126 (BLIND) when pip-audit could not
  audit and 1 only when it reported vulnerabilities. The repository's pins audit clean.
- **Live-plane selftest.** `selftest` proves only the sensors of its plane (`--plane`, default `HARNESS_PLANE`);
  the static container prints where the others are proven instead of reporting them blind. New
  `make harness-selftest-live`, run nightly in CI. Seeded defects for `deps-audit`:
  `harness/sensors/fixtures/deps-audit/` (a pin with a known vulnerability, and a clean pin; `.req` files so
  dependency scanners do not mistake them for the project's requirements).
- First-run impact on existing projects: nightly `deps-audit` starts auditing for real and may report genuine
  vulnerabilities; where the network is missing it shows as BLIND, not FAIL.

## 0.3.1

- **`eval` is blocking** (pipeline stage). It passed on every recorded run (4 of 4 in the ledger, across the tags
  change and the notify service) with recall@5 0.875 and MRR@10 1.0, so the baseline and the tolerance
  (`EVAL_TOLERANCE`, 0.05) are agreed. Only the computational metrics gate: a drop of the optional LLM judge@1 is
  printed and marked `drop (advisory)`, never fails the run. The sensor's kind is now `computational` (coverage no
  longer needs to flag an inferential blocking sensor). First-run impact on existing projects: a ranking change
  that lowers recall@5 or MRR@10 by more than the tolerance now turns the pipeline RED; accept it deliberately by
  promoting `.harness/eval-results.json` to `eval/baseline.json` in the same change (`eval/README.md`).
- **Guides point to the shared consumer.** `harness/skills/new-topic/SKILL.md` step 4 and the
  `kafka-consumer-auto-commit` semgrep message now name `common.events.EventConsumer` (poll, commit after the
  handler, skip malformed events, seek back and back off on errors) instead of asking for a hand-written loop.

## 0.3.0

Three changes from the steering loop (`harness/prompts/next-steps/08-improve-harness.md`), each found while an agent
implemented prompts 02–04 against the reference system.

- **Topology T10 callee-verifies** (ERROR). A service with `TRUSTED_CALLERS` must mount the `service-keys`
  subpath `public`; without it it cannot verify any signature and rejects every call with 401 at runtime. Found while
  adding `notify`: nothing caught a forgotten mount. Seeded defect `t10_callee_without_public_keys.yml`; the clean
  fixture (which had the bug) and the other topology fixtures now mount the public keys, so each seeded defect fires
  only its own rule. Taught in `harness/skills/new-service/SKILL.md` step 3.
- **Semgrep `kafka-consumer-auto-commit`** (ERROR). Rubric R8 ("commit the offset after the side effect") was
  prose only; a `confluent_kafka.Consumer({...})` literal config without `"enable.auto.commit": False` is now caught
  mechanically. Seeded defect `kafka_auto_commit.py`; the clean fixture contains a correct consumer. Paired with the
  new-topic skill.
- **SKIPPED status for unconfigured advisory sensors.** Sensor exit code 125 means "deliberately not configured
  here"; the runner reports SKIP, lists it under *Skipped (not configured)* with the sensor's own hint, keeps it out
  of every stats rate (new `skipped` column) and never fails a stage. A blocking sensor that exits 125 is BLIND.
  The review agent is now opt-in: `LLM_BASE_URL` defaults to empty → SKIPPED; set but unreachable → BLIND (before,
  "no LLM" and "LLM down" were both BLIND, which made `harness-stats` recommend fixing an environment nobody set up).
  `./run.sh --llm` sets `LLM_BASE_URL` for its run and prints the `.env` line that keeps it on.
- Runner image tag `air-harness-runner:0.3.0`.

Expected first-run impact on existing projects:
- T10 fires once per callee that does not mount `public` — each one is a real 401-on-every-call bug.
- `kafka-consumer-auto-commit` fires on consumers left on librdkafka's default; fix by disabling auto-commit and
  committing after the write.
- Projects that relied on the old `LLM_BASE_URL` default (`http://host.docker.internal:11434/v1`) must now set it in
  `.env`; until then the review agent reports SKIPPED instead of reviewing.

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
