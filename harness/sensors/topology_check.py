#!/usr/bin/env python3
"""Topology sensor: the compose file *is* the architecture; check it against itself.

Computational, deterministic, no network, ~100 ms. Output is written for an agent to act on:
one finding per line, each with the rule, the location and the concrete fix.

Rules
  T1 caller-trusted   A service whose env points at http://X:port must be in X's TRUSTED_CALLERS
  T2 key-provisioned  Every service that mounts a service-keys subpath, and every TRUSTED_CALLERS
                      entry, must be in the service-keys one-shot's key list
  T3 default-drift    The same ${VAR} must have the same default everywhere it is used
  T4 migrate-first    A service with DB_DSN must (effectively, after YAML merges) depend on migrate
  T5 topics-first     A service with KAFKA_BOOTSTRAP should depend on kafka-init (topics are not auto-created)
  T6 pinned-images    No :latest / untagged images; flag frozen registries
  T7 alerts-present   Every long-running application service (has `build:`) has rules in the alerts file
  T8 env-documented   Every ${VAR} the compose file reads is listed in the env example file
  T9 data-outside-repo  No writable bind mount into the repository (persistent data lives under DATA_DIR)

T7/T8 read their file paths from the compose file itself (ignored by compose):
  x-harness: { alerts: infra/prometheus/alerts.yml, env_example: .env.example }
Paths are relative to the working directory (the repository root). Services in a dev profile
(TOPOLOGY_DEV_PROFILES) are test/ops tooling, not the deployed architecture: T1, T4-T7 and T9 skip them.

Exit code: 1 if any error, else 0. Warnings never fail the build, except with --strict (used by selftest
so that seeded defects for warning rules prove the rule can fire).
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

URL_RE = re.compile(r"https?://([a-z0-9][a-z0-9-]*):\d+")
VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)(:?-)([^${}]*)\}")
ANY_VAR_RE = re.compile(r"(?<!\$)\$\{([A-Z0-9_]+)")          # $${X} is a literal for the container shell
FROZEN_REGISTRIES = ("bitnamilegacy/",)
NOT_SERVICES = {"localhost", "host.docker.internal"}
DEV_PROFILES = set(os.environ.get("TOPOLOGY_DEV_PROFILES", "admin,local-llm,e2e,tools").split(","))

findings: list[tuple[str, str, str, str, str]] = []


def report(sev: str, rule: str, where: str, msg: str, fix: str) -> None:
    findings.append((sev, rule, where, msg, fix))


def resolve_defaults(s: str) -> str:
    """Replace ${VAR:-default} / ${VAR-default} with the default, innermost first."""
    prev = None
    while prev != s:
        prev, s = s, VAR_RE.sub(lambda m: m.group(3), s)
    return s


def env_of(svc: dict) -> dict[str, str]:
    env = svc.get("environment") or {}
    if isinstance(env, list):
        env = dict(e.split("=", 1) if "=" in e else (e, "") for e in env)
    return {k: "" if v is None else str(v) for k, v in env.items()}


def key_subpaths(svc: dict) -> list[str]:
    out = []
    for v in svc.get("volumes") or []:
        if isinstance(v, dict) and v.get("source") == "service-keys":
            sub = (v.get("volume") or {}).get("subpath")
            if sub and sub != "public":
                out.append(sub)
    return out


def code_lines(raw: str):
    """(lineno, line) with YAML comments removed: variables in comments are documentation, not usage."""
    for lineno, line in enumerate(raw.splitlines(), 1):
        if not line.lstrip().startswith("#"):
            yield lineno, re.split(r"\s#", line, maxsplit=1)[0]


def is_dev(svc: dict) -> bool:
    return bool(DEV_PROFILES & set(svc.get("profiles") or []))


def depends(svc: dict) -> set[str]:
    d = svc.get("depends_on") or []
    return set(d) if isinstance(d, list) else set(d.keys())


def main(compose_path: str, strict: bool = False) -> int:
    raw = Path(compose_path).read_text()
    doc = yaml.safe_load(raw)  # SafeLoader resolves << merge keys, so depends_on is the effective one
    services: dict = doc.get("services") or {}

    trusted = {
        name: {c.strip() for c in env_of(s).get("TRUSTED_CALLERS", "").split(",") if c.strip()}
        for name, s in services.items()
        if "TRUSTED_CALLERS" in env_of(s)
    }

    keys_svc = services.get("service-keys", {})
    ep = keys_svc.get("entrypoint") or []
    key_list = set(ep[ep.index("/keys") + 1:]) if "/keys" in ep else set()

    # T1 caller-trusted
    for name, s in services.items():
        if is_dev(s):
            continue
        for var, val in env_of(s).items():
            for target in URL_RE.findall(resolve_defaults(val)):
                if target in NOT_SERVICES or target == name or target not in trusted:
                    continue
                if name not in trusted[target]:
                    report("ERROR", "T1 caller-trusted", f"services.{name}.environment.{var}",
                           f"{name} calls {target}, but {target}.TRUSTED_CALLERS={sorted(trusted[target])}; "
                           f"the call will be rejected at runtime",
                           f"add '{name}' to services.{target}.environment.TRUSTED_CALLERS, "
                           f"or remove {var} from {name} if the call is not intended")
                if key_list and name not in key_subpaths(s):
                    report("ERROR", "T2 key-provisioned", f"services.{name}.volumes",
                           f"{name} calls {target} but does not mount its own key (subpath '{name}'), "
                           f"so it cannot sign",
                           f"mount service-keys with volume.subpath: {name} at /run/keys/self "
                           f"(see harness/skills/new-service/SKILL.md)")

    # T2 key-provisioned
    if key_list:
        for name, s in services.items():
            for sub in key_subpaths(s):
                if sub not in key_list:
                    report("ERROR", "T2 key-provisioned", f"services.{name}.volumes",
                           f"{name} mounts key subpath '{sub}' that service-keys never generates",
                           f"append \"{sub}\" to services.service-keys.entrypoint")
                elif sub != name:
                    report("WARN", "T2 key-provisioned", f"services.{name}.volumes",
                           f"{name} signs as '{sub}' (shares another identity)",
                           "give each deployable its own key unless sharing is deliberate; record why in AGENTS.md")
        for callee, callers in trusted.items():
            for c in callers - key_list:
                report("ERROR", "T2 key-provisioned", f"services.{callee}.environment.TRUSTED_CALLERS",
                       f"'{c}' is trusted by {callee} but has no key, so it can never authenticate",
                       f"add \"{c}\" to services.service-keys.entrypoint, or drop it from TRUSTED_CALLERS")

    # T3 default-drift (scan raw text: defaults are lost once YAML is parsed)
    defaults: dict[str, dict[tuple[str, str], list[int]]] = defaultdict(lambda: defaultdict(list))
    for lineno, line in code_lines(raw):
        for m in VAR_RE.finditer(line):
            defaults[m.group(1)][(m.group(2), m.group(3))].append(lineno)
    for var, variants in defaults.items():
        values = {d for (_, d) in variants}
        if len(values) > 1:
            where = "; ".join(f"'{d}' at line {','.join(map(str, ls))}" for (_, d), ls in variants.items())
            report("ERROR", "T3 default-drift", f"${{{var}}}",
                   f"{var} has different defaults: {where}",
                   f"use one default for {var}, or split it into two variables with distinct names")
        elif len({op for (op, _) in variants}) > 1:
            report("WARN", "T3 default-drift", f"${{{var}}}",
                   f"{var} mixes ':-' and '-' (empty value means 'default' in one place, 'off' in another)",
                   "pick one operator; '-' only where an empty value deliberately disables the feature")

    # T4 migrate-first / T5 topics-first
    for name, s in services.items():
        if is_dev(s) or name == "migrate":
            continue
        env, deps = env_of(s), depends(s)
        if "DB_DSN" in env and "migrate" not in deps:
            report("ERROR", "T4 migrate-first", f"services.{name}.depends_on",
                   f"{name} uses DB_DSN but does not wait for migrate (an explicit depends_on replaces "
                   f"the one merged from an anchor)",
                   f"add 'migrate: {{ condition: service_completed_successfully }}' to services.{name}.depends_on")
        if "KAFKA_BOOTSTRAP" in env and not deps & {"kafka-init"}:
            report("WARN", "T5 topics-first", f"services.{name}.depends_on",
                   f"{name} uses Kafka but does not wait for kafka-init; on a fresh volume its topic may not exist yet",
                   f"add 'kafka-init: {{ condition: service_completed_successfully }}' to services.{name}.depends_on")

    # T6 pinned-images
    for name, s in services.items():
        img = s.get("image")
        if not img or is_dev(s):                                 # dev-only tooling: not shipped
            continue
        resolved = resolve_defaults(str(img))
        repo, _, tag = resolved.rpartition(":") if ":" in resolved.split("/")[-1] else (resolved, "", "")
        if not tag or tag == "latest":
            report("WARN", "T6 pinned-images", f"services.{name}.image",
                   f"{resolved} is not pinned; builds are not reproducible and the agent cannot reason about versions",
                   "pin a version (ideally a digest) behind a ${NAME_TAG:-x.y.z} variable")
        if resolved.startswith(FROZEN_REGISTRIES):
            report("WARN", "T6 pinned-images", f"services.{name}.image",
                   f"{resolved} comes from a frozen archive repository (no further security updates)",
                   "move to a maintained image; check the uid/data-path layout the storage-init step assumes")

    ext = doc.get("x-harness") or {}

    # T7 alerts-present
    if ext.get("alerts"):
        alerts_path = Path(ext["alerts"])
        alerts = alerts_path.read_text() if alerts_path.exists() else ""
        if not alerts:
            report("ERROR", "T7 alerts-present", "x-harness.alerts",
                   f"alerts file {alerts_path} does not exist", "create it, or fix the path in x-harness.alerts")
        for name, s in services.items():
            long_running = s.get("restart") in ("always", "unless-stopped", "on-failure")
            if alerts and "build" in s and long_running and not s.get("profiles") \
                    and f'job="{name}"' not in alerts:
                report("ERROR", "T7 alerts-present", f"services.{name}",
                       f"{name} has no alert rules (no job=\"{name}\" in {alerts_path})",
                       f"add up / error-rate / latency rules for job=\"{name}\" to {alerts_path} and a "
                       f"scrape job to the Prometheus config next to it")

    # T8 env-documented
    if ext.get("env_example"):
        ex_path = Path(ext["env_example"])
        documented = set(re.findall(r"^\s*([A-Z0-9_]+)=", ex_path.read_text(), re.M)) if ex_path.exists() else set()
        used: dict[str, int] = {}
        for lineno, line in code_lines(raw):
            for m in ANY_VAR_RE.finditer(line):
                used.setdefault(m.group(1), lineno)
        for var, lineno in sorted(used.items()):
            if var not in documented:
                report("ERROR", "T8 env-documented", f"${{{var}}} (line {lineno})",
                       f"{var} is read by compose but not listed in {ex_path}",
                       f"add '{var}=<default>  # what it controls' to {ex_path}")

    # T9 data-outside-repo
    for name, s in services.items():
        if is_dev(s):
            continue
        for v in s.get("volumes") or []:
            src, ro = (v.get("source", ""), v.get("read_only", False)) if isinstance(v, dict) else \
                      (v.split(":")[0], v.split(":")[-1] in ("ro", "z,ro", "ro,z") and v.count(":") >= 2)
            if str(src).startswith((".", "/work")) and not ro:
                report("ERROR", "T9 data-outside-repo", f"services.{name}.volumes",
                       f"{name} mounts {src} from the repository writable; data written there ends up in the repo",
                       "mount it read-only (:ro), or move the data under ${DATA_DIR:-...}")

    order = {"ERROR": 0, "WARN": 1}
    for sev, rule, where, msg, fix in sorted(findings, key=lambda f: (order[f[0]], f[1], f[2])):
        print(f"{sev:5} {rule:20} {where}\n      what: {msg}\n      fix:  {fix}")
    errors = sum(1 for f in findings if f[0] == "ERROR")
    print(f"topology: {len(services)} services, {errors} errors, {len(findings) - errors} warnings")
    return 1 if errors or (strict and findings) else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--strict"]
    sys.exit(main(args[0] if args else "docker-compose.yml", strict="--strict" in sys.argv[1:]))
