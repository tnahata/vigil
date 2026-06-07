"""Structured (JSON-line) logging for the worker. Reads the `vigil` dict that
StageTimer attaches via `extra={"vigil": {...}}` and flattens it into the line.
"""
from __future__ import annotations

import json
import logging
import sys


class VigilFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        vigil = getattr(record, "vigil", None)
        if isinstance(vigil, dict):
            base.update(vigil)
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base)


# Substrings of repetitive, cosmetic LiveKit log lines that bury the routing logs
# in console mode. The 'flushing vad' WARNING fires on nearly every turn when STT
# endpointing is more eager than VAD -- it is benign (the transcript is already
# committed; only VAD state is reset). Other warnings are kept.
_LIVEKIT_NOISE = ("flushing vad",)


class _DropLiveKitNoise(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # False -> drop
        msg = record.getMessage()
        return not any(n in msg for n in _LIVEKIT_NOISE)


def _quiet_livekit_noise() -> None:
    """Drop the high-frequency cosmetic LiveKit warnings. Attached to the emitting
    logger ('livekit.agents') so the record is filtered before it propagates to
    the CLI's root handler. Idempotent."""
    lk = logging.getLogger("livekit.agents")
    if not any(isinstance(f, _DropLiveKitNoise) for f in lk.filters):
        lk.addFilter(_DropLiveKitNoise())


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(VigilFormatter())
    root = logging.getLogger("vigil")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _quiet_livekit_noise()
