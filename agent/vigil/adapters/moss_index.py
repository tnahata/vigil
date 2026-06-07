"""Adapter for the real in-process Moss retrieval engine.

NOT wired yet: the Moss Python API and the `alpha` direction (expected
0=keyword, 1=semantic) are unverified, and the real protocol index is built on
a teammate's branch. The import is lazy so this module stays importable (and the
core-purity test stays green) -- the FakeIndex is used until Moss is confirmed.
"""
from __future__ import annotations

from ..ports.retrieval import QueryResult  # noqa: F401  (kept for adapter parity)


class MossIndex:
    def __init__(self, index_name: str) -> None:
        self.index_name = index_name

    def query(self, text, *, alpha=0.0, filters=None, top_k=5):
        try:
            import inferedge_moss  # noqa: F401  (lazy import)
        except ImportError as exc:
            raise NotImplementedError(
                "MossIndex is not wired yet. `inferedge-moss` is unavailable and the "
                "real protocol index lives on a teammate's branch. TODO: confirm the "
                "in-process query API and the alpha direction (expected 0=keyword, "
                "1=semantic) via the Moss CLI/REPL before trusting it. Use FakeIndex "
                "(RETRIEVAL_BACKEND=fake) until then."
            ) from exc
        raise NotImplementedError(
            "MossIndex.query: map Moss results -> list[QueryResult] once the API is confirmed."
        )
