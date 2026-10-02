# Harness targets. In the project Makefile: `include harness.mk`
HC := HARNESS_UID=$(shell id -u) HARNESS_GID=$(shell id -g) \
      docker compose -f docker-compose.yml -f compose.harness.yml
H  := python3 harness/harness.py

.PHONY: harness-fast harness-integration harness-pipeline harness-continuous harness-selftest harness-coverage harness-stats

harness-fast:            ## pre-commit: hermetic static sensors (blocking) + review agent (advisory)
	@mkdir -p .harness
	$(HC) run --rm harness run --stage pre-commit
	-$(HC) run --rm harness-live run --stage pre-commit

harness-integration:     ## stack must be up: contract suite
	$(H) run --stage integration --plane host

harness-pipeline:        ## CI after merge: everything, including the slow and the inferential
	@mkdir -p .harness
	$(HC) run --rm harness run --stage pipeline
	$(H) run --stage pipeline --plane host

harness-continuous:      ## nightly: drift (dead code, vulnerable dependencies)
	@mkdir -p .harness
	-$(HC) run --rm harness run --stage continuous
	-$(HC) run --rm harness-live run --stage continuous

harness-selftest:        ## seeded defects: prove the sensors can still fire
	$(HC) run --rm harness selftest

harness-coverage:        ## guide/sensor matrix and feedforward-only / feedback-only gaps
	$(H) coverage

harness-stats:           ## steering loop: what fires often, what never fires
	$(H) stats
