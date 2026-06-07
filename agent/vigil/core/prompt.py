"""Constrained Tier-2 prompt construction. Pure: builds OpenAI-style messages
from the EMT query + retrieved chunks. The system prompt forbids any number not
present in the excerpts (belt; the grounding guard in `grounding.py` is the
suspenders).
"""
from __future__ import annotations

from .models import Doc

SYSTEM = (
    "You are Vigil, an EMT protocol assistant. Answer ONLY using the protocol "
    "excerpts provided below. Cite the protocol_id in brackets for any claim. You "
    "MUST NOT state any dose, number, rate, or measurement that does not appear "
    "verbatim in the excerpts. If the excerpts do not contain the answer, reply "
    "exactly: 'Not in protocol. Contact medical control.' Keep it short and "
    "spoken-friendly (1 to 3 sentences)."
)


def build_messages(query: str, chunks: "list[Doc]") -> "list[dict]":
    context = "\n\n".join(
        f"[{c.protocol_id}] ({c.drug}, {c.population}, {c.indication})\n{c.text}"
        for c in chunks
    )
    user = (
        f"Protocol excerpts:\n{context}\n\n"
        f"EMT question: {query}\n\n"
        "Answer:"
    )
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
