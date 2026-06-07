"""Wake-word detection on the transcript. The trigger is the literal "vigil"."""
from __future__ import annotations

import re

WAKE_WORD = "vigil"
_WAKE_RE = re.compile(r"\bvigil\b", re.IGNORECASE)

# punctuation/space trimmed from the start of the extracted query
_LEADING = " ,.;:!?-\t\n"


def detect_wake(transcript: str) -> bool:
    """True iff the wake word appears as a whole word (case-insensitive)."""
    if not transcript:
        return False
    return _WAKE_RE.search(transcript) is not None


def strip_wake(transcript: str) -> str:
    """Return the query following the LAST wake word, trimmed.

    Handles restarts like "Vigil... uh... Vigil what's the dose". If no wake
    word is present, returns the whole transcript trimmed.
    """
    if not transcript:
        return ""
    matches = list(_WAKE_RE.finditer(transcript))
    if not matches:
        return transcript.strip()
    tail = transcript[matches[-1].end():]
    return tail.strip(_LEADING)
