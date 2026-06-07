"""Per-stage timing + structured logging. Observability is a stated priority:
every pipeline stage emits one log line and records a StageTiming, even on error.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from .models import StageTiming

_NULL_LOGGER = logging.getLogger("vigil.null")
_NULL_LOGGER.addHandler(logging.NullHandler())


class StageTimer:
    """Context manager: times a stage, appends a StageTiming to `sink`, and
    emits one structured log line on exit. Extra fields via `.note(**fields)`.

        with StageTimer("retrieve", log, clock, timings) as st:
            ...
            st.note(doc_id="epi_adult", hit=True)
    """

    def __init__(
        self,
        stage: str,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = time.perf_counter,
        sink: list[StageTiming] | None = None,
    ) -> None:
        self.stage = stage
        self._logger = logger or _NULL_LOGGER
        self._clock = clock
        self._sink = sink if sink is not None else []
        self._fields: dict = {}
        self._t0 = 0.0
        self.ms = 0.0

    def note(self, **fields) -> "StageTimer":
        self._fields.update(fields)
        return self

    def __enter__(self) -> "StageTimer":
        self._t0 = self._clock()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.ms = (self._clock() - self._t0) * 1000.0
        self._sink.append(StageTiming(stage=self.stage, ms=self.ms))
        payload = {"stage": self.stage, "ms": round(self.ms, 3), **self._fields}
        if exc_type is not None:
            payload["error"] = repr(exc)
            self._logger.error("stage_error", extra={"vigil": payload})
        else:
            self._logger.info("stage", extra={"vigil": payload})
        return False  # never suppress exceptions
