#!/usr/bin/env bash
# Removes THIS repo's application containers only. fxconnect's clean.sh removes
# every container on the host, which would also kill the shared Kafka and
# fxconnect's own stack - deliberately not copied.
docker compose down --remove-orphans
docker image prune -f
