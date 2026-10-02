# Harness runner image: the versioned, distributable half of the harness product.
# Projects pin HARNESS_IMAGE; the manifest, guides and project sensors stay in the project repo.
FROM python:3.12-slim

ARG RUFF_VERSION=0.16.10
ARG SEMGREP_VERSION=1.179.0
ARG VULTURE_VERSION=2.16
ARG PIP_AUDIT_VERSION=2.10.1
ARG PYYAML_VERSION=6.0.3
ARG PYTEST_VERSION=9.1.1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git make \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir \
      pyyaml==${PYYAML_VERSION} ruff==${RUFF_VERSION} semgrep==${SEMGREP_VERSION} \
      vulture==${VULTURE_VERSION} pip-audit==${PIP_AUDIT_VERSION} pytest==${PYTEST_VERSION}

# The repo is mounted read-only under another uid: let git read it, and never take optional locks.
RUN git config --system --add safe.directory /work
ENV GIT_OPTIONAL_LOCKS=0 \
    HOME=/tmp \
    RUFF_CACHE_DIR=/tmp/ruff \
    SEMGREP_SEND_METRICS=off \
    SEMGREP_ENABLE_VERSION_CHECK=0 \
    PYTHONDONTWRITEBYTECODE=1

LABEL org.opencontainers.image.title="air-harness-runner" \
      org.opencontainers.image.description="Guides + sensors runner for py-services-pg-kafka projects"

WORKDIR /work
ENTRYPOINT ["python", "/work/harness/harness.py"]
