"""Number-grounding guard for Tier 2. The LLM must never introduce a number
that isn't in the retrieved protocol chunks. We compare numeric VALUES (not
substrings) so "1" is not falsely grounded by "15".
"""
from __future__ import annotations

import re

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _values(text: str) -> set[float]:
    out: set[float] = set()
    for tok in _NUM_RE.findall(text or ""):
        try:
            out.add(float(tok))
        except ValueError:
            pass
    return out


def ungrounded_numbers(text: str, allowed_texts: "list[str]") -> "list[str]":
    """Return the numeric tokens in `text` whose value is absent from every
    string in `allowed_texts`. Empty list => fully grounded.
    """
    allowed: set[float] = set()
    for t in allowed_texts:
        allowed |= _values(t)

    bad: list[str] = []
    for tok in _NUM_RE.findall(text or ""):
        try:
            if float(tok) not in allowed:
                bad.append(tok)
        except ValueError:
            continue
    return bad
