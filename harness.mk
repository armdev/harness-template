# Harness targets. In the project Makefile: `include harness.mk`
# Container planes need only docker; the host plane needs python3 with PyYAML (`make harness-doctor`).
HC := HARNESS_UID=$(shell id -u) HARNESS_GID=$(shell id -g) \
      docker compose -f docker-compose.yml -f compose.harness.yml
H  := python3 harness/harness.py
stage ?= pre-commit

.PHONY: harness-fast harness-static harness-integration harness-pipeline harness-continuous harness-selftest harness-coverage \
        harness-stats harness-list harness-one harness-test harness-build harness-doctor

harness-fast:            ## pre-commit: hermetic static sensors (blocking) + review agent (advisory)
	@mkdir -p .harness
	$(HC) run --rm harness run --stage pre-commit
	-$(HC) run --rm harness-live run --stage pre-commit

harness-static:          ## blocking static sensors only (git pre-commit hook, agent Stop hook)
	@mkdir -p .harness
	$(HC) run --rm -T harness run --stage pre-commit --plane static

harness-integration: harness-doctor   ## stack must be up: unit + contract suite
	@mkdir -p .harness
	$(H) run --stage integration --plane host

harness-pipeline: harness-doctor      ## CI after merge: everything, including the slow and the inferential
	@mkdir -p .harness
	$(HC) run --rm harness run --stage pipeline
	$(H) run --stage pipeline --plane host

harness-continuous:      ## nightly: drift (dead code, vulnerable dependencies)
	@mkdir -p .harness
	-$(HC) run --rm harness run --stage continuous
	-$(HC) run --rm harness-live run --stage continuous

harness-one:             ## one container sensor: make harness-one s=topology [stage=pipeline]
	@mkdir -p .harness
	$(HC) run --rm harness run --stage $(stage) --only $(s) || \
	  { rc=$$?; [ $$rc = 3 ] || exit $$rc; $(HC) run --rm harness-live run --stage $(stage) --only $(s); }

harness-selftest:        ## seeded defects: prove the sensors can still fire (and stay quiet on clean code)
	@mkdir -p .harness
	$(HC) run --rm harness selftest

harness-coverage:        ## guide/sensor matrix and feedforward-only / feedback-only gaps
	$(HC) run --rm harness coverage

harness-stats:           ## steering loop: what fires often, what never fires
	$(HC) run --rm harness stats

harness-list:            ## every sensor: stage, plane, blocking, command
	$(HC) run --rm harness list

harness-test:            ## unit tests and lint of the harness itself
	$(HC) run --rm --entrypoint sh harness -c \
	  'ruff check --output-format=concise harness && pytest -q -p no:cacheprovider harness/tests'

harness-build:           ## (re)build the runner image
	$(HC) --profile harness build harness

harness-doctor:          ## host plane prerequisites
	@python3 -c 'import yaml' 2>/dev/null || { echo "host plane needs python3 + PyYAML: pip install pyyaml"; exit 1; }
	@docker compose version >/dev/null || { echo "docker compose v2 is required"; exit 1; }
