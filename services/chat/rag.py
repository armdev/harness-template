"""The fixed retrieval pipeline behind a chat answer, as pure functions: no I/O, so each step is testable.

  question → keywords → search (OR of the keywords) → graph (neighbours of the best hits) → content (full text)
           → prompt with the numbered posts → model → answer citing [#id]
"""
from __future__ import annotations

import json
import re

STOPWORDS = frozenset({
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by", "can",
    "could", "did", "do", "does", "doing", "for", "from", "get", "got", "had", "has", "have", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "me", "more", "most", "my", "no", "not", "of", "on", "or", "our", "please",
    "should", "so", "some", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this",
    "those", "to", "too", "us", "was", "we", "were", "what", "when", "where", "which", "who", "whom", "why", "will",
    "with", "would", "you", "your", "tell", "explain", "show", "give", "find", "know", "want", "need", "like",
    "posts", "post", "write", "wrote", "written",
})

SYSTEM_PROMPT = """You are the assistant of a knowledge base of short posts. Answer the user's question using only \
the posts below. Cite every post you use as [#id] right after the sentence it supports, for example [#12]. If the \
posts do not contain the answer, say so in one sentence and suggest what to search for instead. Never invent posts, \
authors or facts. Be concise: a few sentences or a short list.

Posts:
"""

MAX_BODY_CHARS = 1500           # per post in the prompt; the posts are short, this bounds a pathological one
MAX_HISTORY = 8                 # earlier turns sent to the model with the new question


def keywords(text: str, limit: int = 12) -> list[str]:
    """Distinct content words of a question, in order."""
    seen: list[str] = []
    for w in re.findall(r"[a-z0-9][a-z0-9-]*[a-z0-9]|[a-z0-9]", text.lower()):
        if len(w) > 1 and w not in STOPWORDS and w not in seen:
            seen.append(w)
    return seen[:limit]


def retrieval_words(user_turns: list[str]) -> list[str]:
    """Keywords of the latest question; a short follow-up ("who wrote it?") borrows the previous question's."""
    words = keywords(user_turns[-1])
    if len(words) < 3 and len(user_turns) > 1:
        words += [w for w in keywords(user_turns[-2]) if w not in words]
    return words[:12]


def search_query(words: list[str]) -> str:
    """websearch_to_tsquery syntax: any of the words (the search service ranks posts matching more of them higher)."""
    return " or ".join(words)


def context_block(sources: list[dict]) -> str:
    parts = []
    for s in sources:
        tags = ", ".join(s["tags"]) or "none"
        parts.append(f"[#{s['id']}] {s['title']} (by @{s['author']}; tags: {tags})\n{s['body'][:MAX_BODY_CHARS]}")
    return "\n\n".join(parts)


def build_messages(history: list[dict], sources: list[dict]) -> list[dict]:
    """System prompt with the numbered posts, then the conversation (latest MAX_HISTORY turns)."""
    return [{"role": "system", "content": SYSTEM_PROMPT + context_block(sources)}, *history[-MAX_HISTORY:]]


def citations(answer: str, sources: list[dict]) -> list[int]:
    """Ids cited as [#id] that are among the sources, in order of first citation; anything else is ignored."""
    known, out = {s["id"] for s in sources}, []
    for m in re.finditer(r"\[#(\d+)\]", answer):
        i = int(m.group(1))
        if i in known and i not in out:
            out.append(i)
    return out


def fallback_answer(sources: list[dict], reason: str) -> str:
    """What the user gets without a model: the retrieved posts, cited, so the answer is still useful."""
    lines = [f"No language model answered ({reason}). The most relevant posts:"]
    lines += [f"- {s['title']} [#{s['id']}]" for s in sources]
    return "\n".join(lines)


NO_SOURCES = "I found no posts about that. Try other words, or browse the tags on the Analyze page."


def event(name: str, data) -> str:
    """One server-sent event."""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
