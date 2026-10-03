#!/usr/bin/env python3
"""Search quality sensor. IR metrics are computational; the optional LLM judge is inferential.

Seeds eval/corpus.yaml through the public API (once per corpus version), runs every query, and compares
recall@5 and MRR@10 with eval/baseline.json. Exit 1 when one of them drops by more than EVAL_TOLERANCE (blocking).
judge@1 (LLM) is reported against its baseline but never fails the run: it is inferential and model-dependent.
Writes $EVAL_OUT/eval-report.md (for the agent) and $EVAL_OUT/eval-results.json (to promote to a baseline).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8080")
OUT = Path(os.environ.get("EVAL_OUT", ".harness"))
TOLERANCE = float(os.environ.get("EVAL_TOLERANCE", "0.05"))
BASELINE = Path(os.environ.get("EVAL_BASELINE", HERE / "baseline.json"))   # the harness selftest swaps in fixtures
JUDGE_URL = os.environ.get("JUDGE_BASE_URL", "").rstrip("/")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen3:8b")
JUDGE_KEY = os.environ.get("JUDGE_API_KEY", "not-needed")
JUDGE_PROMPT = Path(os.environ.get("JUDGE_PROMPT", "harness/prompts/judge.md"))
GATED = ("recall@5", "mrr@10")                           # computational metrics; only these can fail the run


def seed(api: httpx.Client, corpus: dict, author: str) -> dict[int, str]:
    """Create the corpus if this version is not indexed yet. Returns post id -> doc key."""
    titles = {d["title"]: d["key"] for d in corpus["docs"]}
    if not existing(api, author, titles):
        for d in corpus["docs"]:
            api.post("/api/posts", json={"title": d["title"], "body": d["body"], "author": author}).raise_for_status()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:                   # indexing is asynchronous (Kafka)
        ids = existing(api, author, titles)
        if len(ids) == len(titles):
            return ids
        time.sleep(0.5)
    sys.exit(f"eval: corpus not fully indexed after 60s ({len(existing(api, author, titles))}/{len(titles)})")


def existing(api: httpx.Client, author: str, titles: dict[str, str]) -> dict[int, str]:
    found: dict[int, str] = {}
    for title, key in titles.items():
        for h in api.get("/api/search", params={"q": title, "author": author, "limit": 50}).json()["hits"]:
            if h["title"] == title:
                found[h["id"]] = key
    return found


def judge(query: str, title: str, body: str) -> int | None:
    """0-3 relevance grade from an LLM, or None when no judge is configured or it misbehaves."""
    if not JUDGE_URL:
        return None
    req = {"model": JUDGE_MODEL, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
           "messages": [{"role": "system", "content": JUDGE_PROMPT.read_text()},
                        {"role": "user", "content": json.dumps({"query": query, "title": title, "body": body})}]}
    try:
        r = httpx.post(f"{JUDGE_URL}/chat/completions", json=req, timeout=120,
                       headers={"Authorization": f"Bearer {JUDGE_KEY}"})
        text = r.json()["choices"][0]["message"]["content"]
        return int(json.loads(text[text.find("{"): text.rfind("}") + 1])["grade"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None


def main() -> int:
    corpus = yaml.safe_load((HERE / "corpus.yaml").read_text())
    docs = {d["key"]: d for d in corpus["docs"]}
    author = f"eval-{corpus['version']}"
    rows, judged = [], []
    with httpx.Client(base_url=GATEWAY, timeout=10) as api:
        ids = seed(api, corpus, author)
        for item in corpus["queries"]:
            hits = api.get("/api/search", params={"q": item["q"], "author": author, "limit": 10}).json()["hits"]
            ranked = [ids.get(h["id"]) for h in hits]
            relevant = set(item["relevant"])
            recall5 = len(relevant & set(ranked[:5])) / len(relevant)
            rr = next((1 / (i + 1) for i, k in enumerate(ranked) if k in relevant), 0.0)
            top = ranked[0] if ranked else None
            grade = judge(item["q"], docs[top]["title"], docs[top]["body"]) if top else None
            if grade is not None:
                judged.append(grade)
            rows.append({"q": item["q"], "recall@5": recall5, "rr": rr, "top": top, "judge": grade})

    n = len(rows)
    metrics = {"recall@5": round(sum(r["recall@5"] for r in rows) / n, 4),
               "mrr@10": round(sum(r["rr"] for r in rows) / n, 4)}
    if judged:
        metrics["judge@1"] = round(sum(judged) / (3 * len(judged)), 4)

    baseline = json.loads(BASELINE.read_text())["metrics"] if BASELINE.exists() else {}
    dropped = [k for k, v in metrics.items() if k in baseline and v < baseline[k] - TOLERANCE]
    regressions = [k for k in dropped if k in GATED]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eval-results.json").write_text(json.dumps({"corpus": corpus["version"], "metrics": metrics}, indent=2))
    lines = [f"# Search eval — corpus {corpus['version']}", "",
             "| metric | now | baseline | |", "|---|---|---|---|"]
    for k, v in metrics.items():
        b = baseline.get(k)
        flag = "REGRESSION" if k in regressions else "drop (advisory)" if k in dropped else "new" if b is None else ""
        lines.append(f"| {k} | {v:.3f} | {'-' if b is None else f'{b:.3f}'} | {flag} |")
    lines += ["", "| query | recall@5 | RR | top | judge |", "|---|---|---|---|---|"]
    lines += [f"| {r['q']} | {r['recall@5']:.2f} | {r['rr']:.2f} | {r['top'] or '-'} | "
              f"{'-' if r['judge'] is None else r['judge']} |" for r in rows]
    lines += ["", f"Tolerance {TOLERANCE}. To accept new numbers deliberately: copy eval-results.json over "
              "eval/baseline.json in the same change and say why in the PR."]
    (OUT / "eval-report.md").write_text("\n".join(lines) + "\n")

    print("\n".join(lines[:3 + len(metrics) + 1]))
    worst = sorted(rows, key=lambda r: (r["rr"], r["recall@5"]))[:3]
    for r in worst:
        if r["rr"] < 1:
            print(f"weak query: {r['q']!r} recall@5={r['recall@5']:.2f} rr={r['rr']:.2f} top={r['top']}")
    for k in sorted(set(dropped) - set(regressions)):
        print(f"eval: {k} dropped (> {TOLERANCE} below baseline) — advisory, does not fail the run")
    if regressions:
        print(f"eval: regression in {', '.join(regressions)} (> {TOLERANCE} below baseline)")
        return 1
    print(f"eval: ok ({n} queries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
