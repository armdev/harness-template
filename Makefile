# haytarar — everything runs through docker compose. `make help` lists the targets.
-include .env
DATA_DIR ?= /var/tmp/haytarar
LLM_MODEL ?= qwen3:8b
export HARNESS_UID := $(shell id -u)
export HARNESS_GID := $(shell id -g)
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help up up-observability down ps logs build test contract eval llm clean purge

help:                    ## list targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-22s %s\n", $$1, $$2}'

build:                   ## build all images (application, tools, harness)
	$(COMPOSE) --profile tools build
	$(COMPOSE) -f docker-compose.yml -f compose.harness.yml --profile harness build harness

up:                      ## start the stack and wait until every service is healthy
	$(COMPOSE) up -d --build --wait

up-observability:        ## stack + Prometheus on :9090
	$(COMPOSE) --profile observability up -d --build --wait

down:                    ## stop the stack (data in DATA_DIR is kept)
	$(COMPOSE) --profile observability --profile local-llm down --remove-orphans

ps:                      ## service status
	$(COMPOSE) ps -a

logs:                    ## follow logs: make logs s=content
	$(COMPOSE) logs -f --tail=200 $(s)

test:                    ## unit tests (no network)
	$(COMPOSE) --profile tools run --rm --build unit

contract:                ## contract suite against the running stack (the specification)
	$(COMPOSE) --profile tools run --rm --build contract

eval:                    ## search quality against eval/baseline.json; report in .harness/eval-report.md
	@mkdir -p .harness
	$(COMPOSE) --profile tools run --rm --build eval

llm:                     ## start the local LLM and pull the review model
	$(COMPOSE) --profile local-llm up -d ollama
	$(COMPOSE) --profile local-llm exec ollama ollama pull $(strip $(LLM_MODEL))

clean:                   ## stop the stack and drop compose volumes (service keys); DATA_DIR is kept
	$(COMPOSE) --profile observability --profile local-llm --profile tools down -v --remove-orphans

purge: clean             ## clean + delete DATA_DIR contents (database, topics, models)
	@printf 'Delete everything under %s? [y/N] ' "$(strip $(DATA_DIR))"; read ans; [ "$$ans" = y ]
	docker run --rm -v "$(strip $(DATA_DIR)):/data" busybox:1.37 sh -c 'rm -rf /data/postgres /data/kafka /data/ollama'

include harness.mk
