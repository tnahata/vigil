"""Vigil LiveKit worker -- wires real adapters to the pure pipeline.

This is the ONLY edge that touches LiveKit. The deterministic Tier-1 logic lives
in vigil.core and never imports livekit, so the dose number can never come from a
model. The AgentSession is built with NO `llm=`, so it never auto-generates speech;
every spoken response is an explicit `session.say()` of either the verbatim Tier-1
`spoken_form` or the constrained, ground-checked Tier-2 text.

Run a local mic<->speaker loop (no phone needed) with creds in agent/.env:

    python agent.py console

We react to a COMPLETED user turn via `VigilAgent.on_user_turn_completed`, NOT to
each raw STT final. The turn-detector model aggregates the whole utterance across
natural pauses, so "Vigil ... what's the epi dose for anaphylaxis" arrives as one
transcript instead of being split into fragments that each miss the wake word.
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
    StopResponse,
    WorkerOptions,
    cli,
    inference,
)

# --- Plugin imports MUST happen at module top-level (the main thread). -------------
# LiveKit plugins call Plugin.register_plugin()/_InferenceRunner.register_runner() at
# import time, and those raise "must be registered on the main thread" if first
# imported from the job-runner thread (which is where entrypoint() runs in console/
# dev mode). Importing here registers them on the main thread; the .load()/() model
# constructors below are then safe to call inside the worker thread.
try:
    from livekit.plugins import silero as _silero
except Exception as _exc:  # pragma: no cover - optional plugin
    _silero = None
    logging.getLogger("vigil.agent").warning("silero_import_failed: %r", _exc)

try:
    from livekit.plugins.turn_detector.multilingual import (
        MultilingualModel as _MultilingualModel,
    )
except Exception as _exc:  # pragma: no cover - optional plugin
    _MultilingualModel = None
    logging.getLogger("vigil.agent").warning("turn_detector_import_failed: %r", _exc)

try:
    from livekit.plugins import minimax as _minimax
except Exception:  # pragma: no cover - naming varies by version
    try:
        from livekit.plugins import minimax_ai as _minimax
    except Exception as _exc:
        _minimax = None
        logging.getLogger("vigil.agent").warning("minimax_import_failed: %r", _exc)

from vigil.adapters.fake_index import FakeIndex
from vigil.adapters.livekit_channel import LiveKitChannel
from vigil.adapters.livekit_speaker import LiveKitSpeaker
from vigil.adapters.logging_setup import configure_logging
from vigil.adapters.moss_index import MossIndex
from vigil.config import Config, load_config
from vigil.core import wake
from vigil.core.pipeline import handle_transcript, resolve_clarification

log = logging.getLogger("vigil.agent")


def build_index(cfg: Config):
    """MossIndex (real `vigil-protocol`) when RETRIEVAL_BACKEND=moss; else a
    FakeIndex seeded from the SAME real chunks.json (hermetic, no network)."""
    if cfg.retrieval_backend == "moss":
        return MossIndex(cfg.moss_index_name, cfg.moss_project_id, cfg.moss_project_key)
    return FakeIndex.from_chunks_json(cfg.chunks_data_path)


def build_tts(cfg: Config):
    """Minimax TTS, falling back to LiveKit inference TTS if it's unavailable."""
    if (cfg.tts_provider or "minimax").lower() == "minimax" and _minimax is not None:
        try:
            # Pass base_url explicitly: the plugin appends /v1/t2a_v2, so it must NOT
            # inherit MINIMAX_BASE_URL (which carries /v1 for the LLM) -> 404 otherwise.
            return _minimax.TTS(
                base_url=cfg.minimax_tts_base_url,
                model=cfg.minimax_tts_model,
                voice=cfg.minimax_tts_voice,
                # PCM -> LiveKit's AudioEmitter treats it as raw samples and skips the
                # PyAV decoder; MP3 over the Minimax WS intermittently raises
                # av.error.InvalidDataError ("Invalid data found when processing input").
                audio_format=cfg.minimax_tts_format,
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
    if _silero is None:
        return None
    try:
        return _silero.VAD.load()
    except Exception as exc:  # noqa: BLE001
        log.warning("silero_unavailable", extra={"vigil": {"error": repr(exc)}})
        return None


def _build_turn_detection():
    if _MultilingualModel is None:
        return None
    try:
        return _MultilingualModel()
    except Exception as exc:  # noqa: BLE001
        log.warning("turn_detector_unavailable", extra={"vigil": {"error": repr(exc)}})
        return None


class VigilAgent(Agent):
    """Reacts to a COMPLETED user turn with the deterministic pipeline.

    `on_user_turn_completed` receives the full turn transcript (assembled by the
    turn detector across pauses). The sync, pure pipeline runs in a thread executor
    so a multi-second Tier-2 LLM call never blocks the audio event loop; Tier 1
    stays sub-millisecond. We then `session.say()` the answer and publish the card,
    and raise StopResponse so the LLM-less session never tries to auto-reply.
    """

    def __init__(self, *, cfg: Config, index, synthesizer, channel: LiveKitChannel) -> None:
        super().__init__(
            instructions=(
                "You are Vigil, a reactive EMT dose copilot. You never speak "
                "unprompted. Dose answers are produced deterministically from "
                "protocol retrieval, not by you."
            ),
        )
        self._cfg = cfg
        self._index = index
        self._synthesizer = synthesizer
        self._channel = channel
        # Pending one-shot Tier-1 clarification (set when we asked a question,
        # consumed on the next turn). Cross-turn state lives here, not in core.
        self._pending = None

    async def _speak(self, answer) -> None:  # noqa: ANN001
        await LiveKitSpeaker(self.session).say(answer.spoken_form)
        try:
            await self._channel.publish_card(answer.card)
        except Exception as exc:  # noqa: BLE001 - a card failure must never block the dose
            log.warning("card_publish_failed", extra={"vigil": {"error": repr(exc)}})

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:  # noqa: ANN001
        transcript = (new_message.text_content or "").strip()
        if not transcript:
            raise StopResponse()

        loop = asyncio.get_running_loop()

        # Mid-clarification: this turn is the medic's reply (no wake word needed).
        # If they re-trigger with the wake word instead, drop the pending question
        # and treat it as a fresh query.
        pending = self._pending
        if pending is not None and not wake.detect_wake(transcript):
            self._pending = None  # one-shot: never re-ask
            work = functools.partial(
                resolve_clarification,
                transcript,
                clarification=pending,
                provider_role=self._cfg.provider_role,
                logger=log,
            )
            answer = await loop.run_in_executor(None, work)
            await self._speak(answer)
            raise StopResponse()
        self._pending = None

        work = functools.partial(
            handle_transcript,
            transcript,
            index=self._index,
            synthesizer=self._synthesizer,
            logger=log,
            tier2_alpha=self._cfg.tier2_alpha,
            tier2_top_k=self._cfg.tier2_top_k,
            provider_role=self._cfg.provider_role,
        )
        answer = await loop.run_in_executor(None, work)

        if answer is not None:
            if answer.clarification is not None:
                self._pending = answer.clarification  # remember; await the reply
            await self._speak(answer)

        # No LLM is configured; stop here so the session doesn't attempt a reply.
        raise StopResponse()


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
    # turn_handling={"turn_detection": <model>, ...} is the current API; the bare
    # turn_detection= kwarg is deprecated (removed in v2.0). max_delay raises the
    # hard cap on waiting for more speech so a mid-query pause isn't cut into
    # fragments. turn_detection is added only when the model loaded (else auto-select).
    turn_handling = {"endpointing": {"max_delay": cfg.turn_max_delay}}
    if (td := _build_turn_detection()) is not None:
        turn_handling["turn_detection"] = td
    session_kwargs["turn_handling"] = turn_handling

    session = AgentSession(**session_kwargs)
    channel = LiveKitChannel(ctx.room)
    agent = VigilAgent(cfg=cfg, index=index, synthesizer=synthesizer, channel=channel)

    await session.start(
        agent=agent,
        room=ctx.room,
        # TODO: add noise_cancellation + RoomInputOptions tuning after the live run
        # confirms the installed plugin's API shape.
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
