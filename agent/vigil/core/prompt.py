"""Constrained Tier-2 prompt construction. Pure: builds OpenAI-style messages
from the EMT query + retrieved chunks. The system prompt forbids any number not
present in the excerpts (belt; the grounding guard in `grounding.py` is the
suspenders).
"""
from __future__ import annotations

from .models import Doc

SYSTEM = (
    "You are Vigil, an EMT protocol assistant. Answer the medic's question in ONE "
    "short spoken sentence (at most 25 words), using ONLY the protocol excerpts "
    "below. Answer ONLY what was asked -- do NOT add adverse effects, mechanisms, "
    "monitoring, administration steps, or any extra detail unless the question "
    "explicitly asks for it. Do NOT include protocol IDs, page numbers, or citations "
    "in your answer (it is read aloud). You MUST NOT state any dose, number, rate, or "
    "measurement that does not appear verbatim in the excerpts. If the excerpts do "
    "not contain the answer, reply exactly: 'Not in protocol. Contact medical control.'"
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
