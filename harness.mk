# Harness targets. In the project Makefile: `include harness.mk`
# Container planes need only docker; the host plane needs python3 with PyYAML (`make harness-doctor`).
HC := HARNESS_UID=$(shell id -u) HARNESS_GID=$(shell id -g) \
      docker compose -f docker-compose.yml -f compose.harness.yml
H  := python3 harness/harness.py
stage ?= pre-commit
OUT_DIR := .harness

.PHONY: harness-fast harness-static harness-integration harness-pipeline harness-continuous harness-selftest harness-coverage \
        harness-stats harness-list harness-one harness-test harness-build harness-doctor harness-selftest-live harness-selftest-host

harness-fast:            | $(OUT_DIR) ## pre-commit: hermetic static sensors (blocking) + review agent (advisory)
	$(HC) run --rm harness run --stage pre-commit
	-$(HC) run --rm harness-live run --stage pre-commit

harness-static:          | $(OUT_DIR) ## blocking static sensors only (git pre-commit hook, agent Stop hook)
	$(HC) run --rm -T harness run --stage pre-commit --plane static

harness-integration: harness-doctor | $(OUT_DIR) ## stack must be up: unit + contract suite
	$(H) run --stage integration --plane host

harness-pipeline: harness-doctor | $(OUT_DIR) ## CI after merge: everything, including the slow and the inferential
	$(HC) run --rm harness run --stage pipeline
	$(H) run --stage pipeline --plane host

harness-continuous:      | $(OUT_DIR) ## nightly: drift (dead code, vulnerable dependencies)
	-$(HC) run --rm harness run --stage continuous
	-$(HC) run --rm harness-live run --stage continuous

harness-one:             | $(OUT_DIR) ## one container sensor: make harness-one s=topology [stage=pipeline]
	$(HC) run --rm harness run --stage $(stage) --only $(s) || \
	  { rc=$$?; [ $$rc = 3 ] || exit $$rc; $(HC) run --rm harness-live run --stage $(stage) --only $(s); }

harness-selftest:        | $(OUT_DIR) ## seeded defects: prove the sensors can still fire (and stay quiet on clean code)
	$(HC) run --rm harness selftest

harness-selftest-live:   | $(OUT_DIR) ## seeded defects of the live-plane sensors (needs network: vulnerability database)
	$(HC) run --rm harness-live selftest

harness-selftest-host: harness-doctor | $(OUT_DIR) ## seeded defects of the host-plane sensors (prom-rules: docker; eval: stack up)
	$(H) selftest --plane host

harness-coverage:        | $(OUT_DIR) ## guide/sensor matrix and feedforward-only / feedback-only gaps
	$(HC) run --rm harness coverage

harness-stats:           | $(OUT_DIR) ## steering loop: what fires often, what never fires
	$(HC) run --rm harness stats

harness-list:            | $(OUT_DIR) ## every sensor: stage, plane, blocking, command
	$(HC) run --rm harness list

harness-test:            | $(OUT_DIR) ## unit tests and lint of the harness itself
	$(HC) run --rm --entrypoint sh harness -c \
	  'ruff check --output-format=concise harness && pytest -q -p no:cacheprovider harness/tests'

harness-build:           ## (re)build the runner image
	$(HC) --profile harness build harness

harness-doctor:          ## host plane prerequisites
	@python3 -c 'import yaml' 2>/dev/null || { echo "host plane needs python3 + PyYAML: pip install pyyaml"; exit 1; }
	@docker compose version >/dev/null || { echo "docker compose v2 is required"; exit 1; }

# Create the output directory as the invoking user. If docker creates a missing bind-mount source it is owned
# by root, and the sensor containers (running as HARNESS_UID) can no longer write their results into it.
$(OUT_DIR):
	mkdir -p $@
