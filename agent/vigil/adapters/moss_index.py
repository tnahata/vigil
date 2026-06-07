"""Adapter for the real in-process Moss retrieval engine (index `vigil-protocol`).

Moss's client is async (every op is awaited), but the pipeline calls
`index.query()` synchronously from a thread executor. So this adapter owns a
persistent `MossClient` and a dedicated asyncio loop on a daemon thread: the
index is loaded (and warmed) ONCE in `__init__`, and each sync `query()` hands a
coroutine to that loop via `run_coroutine_threadsafe(...).result()`. That keeps
Moss's "load once, then in-process (<10 ms)" property -- `asyncio.run()` per call
would tear down the loop and force a reload every time.

The core (vigil.core) never imports this; `import moss` lives here in the
adapter layer, outside the purity scan.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import threading

from moss import MossClient, QueryOptions

from ..core.models import Doc
from ..ports.retrieval import QueryResult

log = logging.getLogger("vigil.moss")

# The core speaks "population"; the Moss metadata field is "patient_type".
_FIELD_REMAP = {"population": "patient_type"}


def _to_moss_filter(filters: dict | None):
    """Translate the port's filter dict -> Moss's {field, condition} shape.

      {"drug": {"$eq": x}}                       -> {"field":"drug","condition":{"$eq":x}}
      {"drug": {"$eq": x}, "population": {...}}   -> {"$and":[{...},{...}]}
      {} / None                                  -> None
    The inner condition ({"$eq": ...} / {"$in": [...]}) passes through verbatim.
    """
    if not filters:
        return None
    parts = [
        {"field": _FIELD_REMAP.get(k, k), "condition": cond}
        for k, cond in filters.items()
    ]
    return parts[0] if len(parts) == 1 else {"$and": parts}


def _to_doc(d) -> Doc:
    # A Moss result doc exposes .id, .metadata, .score, .text -- same shape a
    # chunk needs, so Doc.from_chunk is the single mapping for both backends.
    return Doc.from_chunk(
        {"id": d.id, "metadata": dict(d.metadata or {}), "text": getattr(d, "text", "") or ""}
    )


class MossIndex:
    def __init__(
        self,
        index_name: str,
        project_id: str,
        project_key: str,
        *,
        query_timeout: float = 5.0,
        load_timeout: float = 30.0,
    ) -> None:
        if not project_id or not project_key:
            raise ValueError("MossIndex requires MOSS_PROJECT_ID and MOSS_PROJECT_KEY")
        self.index_name = index_name
        self._timeout = query_timeout

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="moss-loop", daemon=True
        )
        self._thread.start()

        self._closed = False
        self._client = MossClient(project_id, project_key)  # sync ctor
        self._submit(self._client.load_index(index_name)).result(timeout=load_timeout)
        self._warm()
        # Release the native index + its threadpool BEFORE interpreter teardown.
        # Without this the daemon loop thread is killed mid-state at exit and the
        # native moss core aborts ("mutex lock failed"). atexit runs while the loop
        # is still alive, so the coroutine can unload cleanly.
        atexit.register(self.close)
        log.info("moss_index_ready", extra={"vigil": {"index": index_name}})

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def close(self) -> None:
        """Unload the index and stop the loop thread for a clean shutdown."""
        if self._closed:
            return
        self._closed = True
        try:
            self._submit(self._client.unload_index(self.index_name)).result(timeout=5)
        except Exception as exc:  # noqa: BLE001 - best-effort; may fail harmlessly at atexit
            log.debug("moss_unload_skipped", extra={"vigil": {"error": repr(exc)}})
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:  # noqa: BLE001
            pass
        self._thread.join(timeout=2.0)
        try:
            self._loop.close()
        except Exception:  # noqa: BLE001
            pass

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _warm(self) -> None:
        """First query lazily spins up the embedding model + thread pool; pay it
        once here so the medic's first real dose query is already at steady state."""
        try:
            self.query(
                "EPINEPHRINE (1:1,000)",
                alpha=0.0,
                filters={"drug": {"$eq": "EPINEPHRINE (1:1,000)"}, "population": {"$eq": "adult"}},
                top_k=1,
            )
        except Exception as exc:  # noqa: BLE001 - warm-up failure must not block startup
            log.warning("moss_warmup_failed", extra={"vigil": {"error": repr(exc)}})

    def query(self, text, *, alpha=0.0, filters=None, top_k=5):
        opts = QueryOptions(top_k=top_k, alpha=alpha, filter=_to_moss_filter(filters))
        res = self._submit(self._client.query(self.index_name, text, opts)).result(
            timeout=self._timeout
        )
        docs = getattr(res, "docs", None) or []
        return [QueryResult(doc=_to_doc(d), score=float(getattr(d, "score", 0.0) or 0.0))
                for d in docs[:top_k]]
