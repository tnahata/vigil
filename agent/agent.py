"""Vigil LiveKit worker -- wires real adapters to the pure pipeline.

This is the ONLY edge that touches LiveKit. The deterministic Tier-1 logic lives
in vigil.core and never imports livekit, so the dose number can never come from a
model. The AgentSession is built with NO `llm=`, so it never auto-generates speech;
every spoken response is an explicit `session.say()` of either the verbatim Tier-1
`spoken_form` or the constrained, ground-checked Tier-2 text.

Run a local mic<->speaker loop (no phone needed) once creds are in agent/.env:

    python agent.py console

NOTE: needs LIVEKIT_API_KEY *and* LIVEKIT_API_SECRET (+ LIVEKIT_URL). The secret is
still pending in .env, so the live run is wired but not yet executed.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os

# Load agent/.env at import time, BEFORE the LiveKit CLI reads the environment.
# In `console`/`dev` mode the worker checks LIVEKIT_URL (ws_url) at startup --
# before our entrypoint() (and thus load_config()'s own load_dotenv()) ever runs --
# so without this the CLI raises "ws_url is required" even though .env has it.
# Anchored to this file's directory so it works regardless of the working dir.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:  # pragma: no cover - dotenv is optional for pure tests
    pass

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    inference,
)

from vigil.adapters.fake_index import FakeIndex
from vigil.adapters.livekit_channel import LiveKitChannel
from vigil.adapters.livekit_speaker import LiveKitSpeaker
from vigil.adapters.logging_setup import configure_logging
from vigil.adapters.moss_index import MossIndex
from vigil.config import Config, load_config
from vigil.core.pipeline import handle_transcript

log = logging.getLogger("vigil.agent")


def build_index(cfg: Config):
    """FakeIndex by default; MossIndex when RETRIEVAL_BACKEND=moss (not wired yet)."""
    if cfg.retrieval_backend == "moss":
        return MossIndex(cfg.moss_index_name)
    return FakeIndex.from_json(cfg.gold_data_path)


def build_tts(cfg: Config):
    """Minimax TTS, falling back to LiveKit inference TTS if it's unavailable
    (e.g. Minimax requires a group id we don't have)."""
    if (cfg.tts_provider or "minimax").lower() == "minimax":
        try:
            try:
                from livekit.plugins import minimax as _mm
            except ImportError:
                from livekit.plugins import minimax_ai as _mm  # naming varies by version
            # Pass base_url explicitly: the plugin appends /v1/t2a_v2, so it must NOT
            # inherit MINIMAX_BASE_URL (which carries /v1 for the LLM) -> 404 otherwise.
            return _mm.TTS(
                base_url=cfg.minimax_tts_base_url,
                model=cfg.minimax_tts_model,
                voice=cfg.minimax_tts_voice,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "minimax_tts_unavailable",
                extra={"vigil": {"error": repr(exc), "fallback": cfg.inference_tts_model}},
            )
    return inference.TTS(cfg.inference_tts_model)


def build_synthesizer(cfg: Config):
    """Minimax Tier-2 synthesizer, or None (Tier 2 then degrades to safe fallback)."""
    if not cfg.minimax_api_key:
        log.warning("minimax_llm_unavailable", extra={"vigil": {"reason": "no_api_key"}})
        return None
    from vigil.adapters.minimax_synth import MinimaxSynthesizer

    return MinimaxSynthesizer(
        api_key=cfg.minimax_api_key,
        base_url=cfg.minimax_base_url,
        model=cfg.minimax_llm_model,
    )


def _build_vad():
    try:
        from livekit.plugins import silero

        return silero.VAD.load()
    except Exception as exc:  # noqa: BLE001
        log.warning("silero_unavailable", extra={"vigil": {"error": repr(exc)}})
        return None


def _build_turn_detection():
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel

        return MultilingualModel()
    except Exception as exc:  # noqa: BLE001
        log.warning("turn_detector_unavailable", extra={"vigil": {"error": repr(exc)}})
        return None


async def entrypoint(ctx: JobContext) -> None:
    configure_logging()
    cfg = load_config()
    index = build_index(cfg)
    synthesizer = build_synthesizer(cfg)

    session_kwargs = {
        "stt": inference.STT(cfg.stt_model, language=cfg.stt_language),
        "tts": build_tts(cfg),
        # No llm= on purpose: the session never auto-replies; we drive all speech.
    }
    if (vad := _build_vad()) is not None:
        session_kwargs["vad"] = vad
    if (td := _build_turn_detection()) is not None:
        session_kwargs["turn_detection"] = td

    session = AgentSession(**session_kwargs)
    speaker = LiveKitSpeaker(session)
    channel = LiveKitChannel(ctx.room)

    async def _respond(transcript: str) -> None:
        loop = asyncio.get_running_loop()
        # Run the (sync, pure) pipeline off the event loop so a Tier-2 LLM call
        # never blocks audio. Tier 1 stays sub-millisecond regardless.
        work = functools.partial(
            handle_transcript,
            transcript,
            index=index,
            synthesizer=synthesizer,
            logger=log,
            tier2_alpha=cfg.tier2_alpha,
            tier2_top_k=cfg.tier2_top_k,
        )
        answer = await loop.run_in_executor(None, work)
        if answer is None:
            return  # no wake word -> stay silent (reactive only)
        await speaker.say(answer.spoken_form)
        await channel.publish_card(answer.card)

    @session.on("user_input_transcribed")
    def on_transcribed(ev) -> None:
        # Final transcripts only. Interim partials (speculative retrieval) deferred.
        if not getattr(ev, "is_final", False):
            return
        asyncio.create_task(_respond(ev.transcript))

    await session.start(
        agent=Agent(
            instructions=(
                "You are Vigil, a reactive EMT dose copilot. You never speak "
                "unprompted. Dose answers are produced deterministically from "
                "protocol retrieval, not by you."
            ),
        ),
        room=ctx.room,
        # TODO: add noise_cancellation + RoomInputOptions tuning after the live run
        # confirms the installed plugin's API shape.
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
