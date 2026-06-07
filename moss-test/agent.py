"""Vigil — hands-free EMT dosage voice copilot.

Data-flow per query:
  STT (LiveKit Inference / deepgram) → on_user_turn_completed
    → [no "vigil"] → StopResponse (ignore)
    → [Tier 1: drug detected] → alias normalize → Moss keyword query (alpha=0)
                              → session.say(spoken_form)  [NO LLM]
    → [Tier 2: soft synthesis] → Moss hybrid query (alpha=0.6)
                               → Minimax LLM (constrained to chunks)
                               → session.say(answer)

The critical safety property: for Tier 1 the LLM is architecturally removed
from the dose path.  Every number the medic hears comes verbatim from the
Moss index document, which comes verbatim from the source protocol PDF.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ChatContext,
    ChatMessage,
    JobContext,
    JobProcess,
    StopResponse,
    cli,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics, silero
from livekit.plugins import minimax
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from moss import MossClient, QueryOptions

from aliases import extract_drug_from_query

logger = logging.getLogger("vigil")

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MOSS_INDEX = os.getenv("MOSS_INDEX_NAME", "vigil-protocol")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_LLM_BASE_URL = os.getenv("MINIMAX_LLM_BASE_URL", "https://api.minimaxi.chat/v1")
MINIMAX_LLM_MODEL = os.getenv("MINIMAX_LLM_MODEL", "MiniMax-Text-01")

# Lightweight PII patterns stripped before any LLM call.
_PII_PATTERNS = [
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),   # phone
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),          # DOB
    re.compile(r"\bSSN:?\s*\d{3}-\d{2}-\d{4}\b", re.I),  # SSN
    re.compile(r"\bMRN:?\s*\w+\b", re.I),                 # medical record number
    re.compile(r"\bDOB:?\s*\S+\b", re.I),                 # explicit DOB label
]

_PEDS_TERMS = frozenset(
    ["peds", "pediatric", "pediatrics", "child", "infant", "baby", "neonatal", "weight", "kg"]
)


def _redact_pii(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _is_peds(query: str) -> bool:
    q = query.lower()
    return any(term in q for term in _PEDS_TERMS)


class VIGILAgent(Agent):
    """Vigil voice agent — deterministic dose path, LLM only for Tier 2."""

    def __init__(self, *, room=None) -> None:
        super().__init__(
            # Inference LLM is configured but never called on Tier 1 — StopResponse
            # is raised before the session's LLM pipeline runs.  Tier 2 calls
            # Minimax directly via openai-compatible client.
            llm=inference.LLM(model="openai/gpt-4.1-mini"),
            instructions=(
                "You are Vigil, an EMT dosage assistant. "
                "Only answer queries triggered by the wake word 'Vigil'. "
                "Never fabricate drug doses, concentrations, or protocol information."
            ),
        )
        self._room = room
        self._moss = MossClient(
            os.getenv("MOSS_PROJECT_ID"),
            os.getenv("MOSS_PROJECT_KEY"),
        )
        self._index_loaded = False
        self._session_has_interacted = False  # gate for speculative retrieval
        self._t_stt_done: float | None = None

    async def on_enter(self) -> None:
        if not self._index_loaded:
            try:
                await self._moss.load_index(MOSS_INDEX)
                self._index_loaded = True
                logger.info("Moss index '%s' loaded", MOSS_INDEX)
            except Exception:
                logger.exception("Failed to preload Moss index")

    # ------------------------------------------------------------------
    # Main routing hook — called after each committed user turn
    # ------------------------------------------------------------------

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        text = (new_message.text_content or "").lower().strip()
        self._t_stt_done = time.monotonic()
        logger.info("STT | %r", text)

        if "vigil" not in text:
            raise StopResponse()

        query = text[text.index("vigil") + len("vigil"):].strip()
        if not query:
            await self.session.say("Ready. What do you need?")
            self._session_has_interacted = True
            raise StopResponse()

        self._session_has_interacted = True
        logger.info("Query | %r", query)

        # Try Tier 1: extract canonical drug → keyword Moss query (alpha=0)
        canonical_drug = extract_drug_from_query(query)
        if canonical_drug:
            result = await self._tier1_query(query, canonical_drug)
            if result is not None:
                spoken, card = result
                t_ret = time.monotonic()
                logger.info(
                    "Tier 1 | drug=%r | %.0f ms",
                    canonical_drug,
                    (t_ret - self._t_stt_done) * 1000,
                )
                await self._publish_card(card)
                await self.session.say(spoken)
                raise StopResponse()

        # Tier 2: hybrid retrieval + Minimax LLM
        await self._tier2_query(query)
        raise StopResponse()

    # ------------------------------------------------------------------
    # Tier 1 — deterministic, verbatim-from-protocol, NO LLM
    # ------------------------------------------------------------------

    async def _tier1_query(
        self, query: str, canonical_drug: str
    ) -> tuple[str, dict] | None:
        await self._ensure_index()
        # NOTE: must match the patient_type vocabulary written by chunk.py
        # ("adult" / "pediatric" / "all") — using "peds" here whiffs every
        # filter and silently falls back to an unfiltered (adult) result.
        population = "pediatric" if _is_peds(query) else "adult"

        # Attempt exact drug + population filter first.
        for filter_opts in [
            {
                "$and": [
                    {"field": "drug", "condition": {"$eq": canonical_drug}},
                    {"field": "patient_type", "condition": {"$eq": population}},
                ]
            },
            # Fall back without population filter (peds entries may be absent).
            {"field": "drug", "condition": {"$eq": canonical_drug}},
        ]:
            try:
                result = await self._moss.query(
                    MOSS_INDEX,
                    canonical_drug,
                    QueryOptions(top_k=1, alpha=0, filter=filter_opts),
                )
            except Exception:
                logger.exception("Tier 1 query failed")
                return None

            docs = getattr(result, "docs", None) or []
            if docs:
                break
        else:
            return None

        doc = docs[0]
        meta = getattr(doc, "metadata", {}) or {}
        spoken_form = meta.get("value_spoken") or getattr(doc, "text", "")
        source = meta.get("source", "protocol")
        page = meta.get("page", "")
        indication = meta.get("indication", "")

        spoken = (
            f"For {canonical_drug.lower()}"
            + (f", {indication}" if indication else "")
            + f": {spoken_form}."
            + (f" Source: {source}, page {page}." if page else "")
        )
        card = {
            "tier": 1,
            "drug": canonical_drug,
            "dose": meta.get("value_machine", getattr(doc, "text", "")),
            "spoken": spoken_form,
            "source": source,
            "page": page,
            "indication": indication,
            "population": meta.get("patient_type", population),
        }
        return spoken, card

    # ------------------------------------------------------------------
    # Tier 2 — hybrid retrieval + Minimax LLM (constrained to chunks)
    # ------------------------------------------------------------------

    async def _tier2_query(self, query: str) -> None:
        await self._ensure_index()
        t0 = time.monotonic()

        try:
            result = await self._moss.query(
                MOSS_INDEX,
                query,
                QueryOptions(top_k=4, alpha=0.6),
            )
        except Exception:
            logger.exception("Tier 2 Moss query failed")
            await self.session.say(
                "I can't access the protocol database right now. Contact medical control."
            )
            return

        t_ret = time.monotonic()
        logger.info("Tier 2 retrieval | %.0f ms", (t_ret - t0) * 1000)

        docs = getattr(result, "docs", None) or []
        if not docs:
            await self.session.say(
                "That information isn't in the protocol. Contact medical control."
            )
            return

        chunks = "\n\n".join(
            f"[{i + 1}] {(getattr(d, 'text', '') or '').strip()}"
            for i, d in enumerate(docs)
        )
        safe_query = _redact_pii(query)

        system = (
            "You are Vigil, an EMT protocol assistant. "
            "Answer using ONLY the protocol chunks below. "
            "Do NOT emit any number not present in the chunks. "
            "Do NOT invent drug names, doses, or indications. "
            "If the answer isn't covered, say: "
            "'Not in protocol — contact medical control.' "
            "Reply in 1-3 plain spoken sentences, no markdown."
        )
        user = f"Protocol chunks:\n{chunks}\n\nQuery: {safe_query}"

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_LLM_BASE_URL)
            resp = await client.chat.completions.create(
                model=MINIMAX_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=150,
                temperature=0.0,
            )
            answer = (resp.choices[0].message.content or "").strip()
            if not answer:
                answer = "Not in protocol — contact medical control."
        except Exception:
            logger.exception("Minimax LLM call failed")
            answer = "I couldn't synthesize a response. Contact medical control."

        t_llm = time.monotonic()
        logger.info(
            "Tier 2 LLM | retrieval+LLM=%.0f ms", (t_llm - t0) * 1000
        )
        await self.session.say(answer)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_index(self) -> None:
        if not self._index_loaded:
            await self._moss.load_index(MOSS_INDEX)
            self._index_loaded = True

    async def _publish_card(self, card: dict) -> None:
        if self._room is None:
            return
        try:
            payload = json.dumps({"type": "vigil_card", "data": card}).encode()
            await self._room.local_participant.publish_data(payload=payload, reliable=True)
        except Exception:
            logger.exception("Failed to publish card")


# ------------------------------------------------------------------
# Server setup
# ------------------------------------------------------------------

server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="vigil")
async def session_entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="multi"),
        # Minimax TTS — text_normalization reads doses correctly ("0.01 mg" etc.)
        tts=minimax.TTS(
            model="speech-02-turbo",
            voice="socialmedia_female_2_v1",
            text_normalization=True,
            api_key=MINIMAX_API_KEY,
        ),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
    )

    await session.start(
        agent=VIGILAgent(room=ctx.room),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    await ctx.connect()

    await session.say(
        "Vigil ready. Say 'Vigil' followed by your question to get a protocol answer."
    )


if __name__ == "__main__":
    cli.run_app(server)
