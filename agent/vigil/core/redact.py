"""Lightweight PII redaction for the Tier-2 LLM path (defense-in-depth).

Conservative regex stripping of obvious identifiers BEFORE any text leaves the
server for the (deferred) Minimax LLM. NOT used on the Tier-1 dose path.
Expand before any real patient use.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\bMRN[:\s#]*\w+\b", re.IGNORECASE), "[MRN]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "[DATE]"),
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out
