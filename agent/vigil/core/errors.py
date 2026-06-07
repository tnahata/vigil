"""Safe-degradation answers. The agent NEVER guesses a dose -- on any miss or
error it falls back to a fixed instruction to contact medical control.
"""
from __future__ import annotations

from .models import Answer, StageTiming, Tier

SAFE_FALLBACK_SPOKEN = "Not in protocol. Contact medical control."


def safe_card(tier: Tier, message: str = SAFE_FALLBACK_SPOKEN) -> dict:
    return {"found": False, "message": message, "tier": tier.value}


def safe_not_in_protocol(
    tier: Tier = Tier.TIER1_DOSE,
    *,
    timings: list[StageTiming] | None = None,
) -> Answer:
    return Answer(
        tier=tier,
        spoken_form=SAFE_FALLBACK_SPOKEN,
        card=safe_card(tier),
        citation=None,
        doc_id=None,
        found=False,
        timings=list(timings) if timings else [],
    )
