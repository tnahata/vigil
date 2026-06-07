"""In-memory deterministic retrieval index. Used by tests and runnable today
with zero network -- it stands in for Moss until the real index is wired.

  alpha == 0  -> pure keyword: alias-aware drug match + indication tiebreak
                 (deterministic; this is the Tier-1 path).
  alpha  > 0  -> hybrid: blend of token-overlap (pseudo-semantic) and keyword,
                 to exercise Tier-2 wiring without embeddings.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core import aliases
from ..core.models import Doc
from ..ports.retrieval import QueryResult

_WORD_RE = re.compile(r"[a-z0-9\-]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _doc_field(doc: Doc, name: str):
    if hasattr(doc, name):
        return getattr(doc, name)
    return doc.metadata.get(name)


def _match_condition(value, cond) -> bool:
    if not isinstance(cond, dict):  # bare value behaves like $eq
        return value == cond
    for op, operand in cond.items():
        if op == "$eq":
            if value != operand:
                return False
        elif op == "$in":
            if value not in operand:
                return False
        elif op == "$and":
            if not all(_match_condition(value, sub) for sub in operand):
                return False
        else:
            raise NotImplementedError(f"FakeIndex: filter operator {op!r} not supported")
    return True


def _matches_filters(doc: Doc, filters: dict) -> bool:
    return all(_match_condition(_doc_field(doc, k), cond) for k, cond in (filters or {}).items())


class FakeIndex:
    def __init__(self, docs: "list[Doc]") -> None:
        self._docs = list(docs)

    @classmethod
    def from_json(cls, path) -> "FakeIndex":
        data = json.loads(Path(path).read_text())
        return cls([Doc.from_dict(d) for d in data])

    @property
    def docs(self) -> "list[Doc]":
        return list(self._docs)

    def query(self, text, *, alpha=0.0, filters=None, top_k=5):
        candidates = [d for d in self._docs if _matches_filters(d, filters or {})]
        query_drug = aliases.extract_drug(text)
        q_tokens = _tokens(text)

        scored: list[QueryResult] = []
        for doc in candidates:
            kw = self._keyword_score(doc, query_drug, q_tokens)
            if alpha <= 0.0:
                score = kw
            else:
                sem = self._overlap_score(doc, q_tokens)
                score = alpha * sem + (1.0 - alpha) * kw
            if score > 0.0:
                scored.append(QueryResult(doc=doc, score=score))

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _keyword_score(doc: Doc, query_drug, q_tokens) -> float:
        # Exact, alias-normalized drug match is the deterministic anchor.
        if query_drug is None or doc.drug != query_drug:
            return 0.0
        score = 1.0
        # Deterministic indication tiebreak (still keyword -- no embeddings),
        # so "epi for anaphylaxis" beats "epi for cardiac arrest".
        ind_tokens = _tokens(doc.indication.replace("_", " "))
        if ind_tokens and (ind_tokens & q_tokens):
            score += 0.5
        return score

    @staticmethod
    def _overlap_score(doc: Doc, q_tokens) -> float:
        doc_tokens = _tokens(f"{doc.text} {doc.drug} {doc.indication}")
        if not q_tokens or not doc_tokens:
            return 0.0
        return len(q_tokens & doc_tokens) / len(q_tokens | doc_tokens)
