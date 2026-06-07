"""Pure decisions for the wake/clarify dialog state machine.

The cross-turn STATE (the sticky listening window, the accumulated buffer, the
pending clarification) lives on the LiveKit adapter (`VigilAgent`), because it is
inherently about wall-clock turns. But the *decision* it makes each turn -- "is
this buffered query worth answering yet, or should I keep listening?" -- is pure
and lives here so it is unit-testable without LiveKit.

Why this matters: with `turn_detection="stt"` the medic's wake word and question
often arrive as SEPARATE turns ("Vigil" <pause> "what's the amiodarone dose"). The
agent buffers across turns within a short window; `query_has_substance` is the gate
that decides whether the buffer so far is a real ask (run the pipeline, speak the
result) or still forming (stay silent, wait for the next fragment) -- which is what
stops bare "Vigil" from blurting "Not in protocol."
"""
from __future__ import annotations

from . import aliases, router


def query_has_substance(buffer: str) -> bool:
    """True if the buffered query is worth routing NOW.

    True when it expresses an ask (dose/synthesis intent) OR names a known drug.
    False for still-forming fragments like "" / "vigil" / "vigil what" / "the
    patient is" -- the agent then keeps listening within the wake window instead
    of answering prematurely.

    Adversarial safety is preserved: "how much rocuronium" HAS intent -> True ->
    the pipeline runs and returns the safe "Not in protocol" fallback, never
    silence-by-omission for a real (if unknown) drug question.
    """
    return router.has_intent(buffer) or aliases.extract_drug(buffer) is not None


def turn_is_fresh_query(reply_text: str) -> bool:
    """While a clarification is pending, decide if THIS turn is a fresh question
    rather than the reply.

    A clarification reply is a bare indication ("stable VT", "bradycardia",
    "the first one") and names NO drug. A turn that names a drug ("what dosage of
    atropine", "epinephrine") is a new question -> the agent abandons the pending
    clarification and routes it fresh. This is what stops a stale clarification
    from swallowing the next query (the live "atropine didn't ask a follow-up"
    bug). `reply_text` should already have the wake word stripped.
    """
    return aliases.extract_drug(reply_text) is not None
