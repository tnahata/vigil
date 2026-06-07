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


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(VigilFormatter())
    root = logging.getLogger("vigil")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
