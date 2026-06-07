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
import time

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
from vigil.core import dialog, wake
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
                # Speak a touch faster -- medics want the dose quickly. Plugin clamps
                # to [0.5, 2.0] and raises outside it, so keep MINIMAX_TTS_SPEED in range.
                speed=cfg.minimax_tts_speed,
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


def _build_turn_detection(cfg: Config):
    """Turn-end detection mode.

    Default "stt": end the turn on the STT provider's (Deepgram) final transcript
    -- deterministic and prompt, which is what we want. The "multilingual" EOU
    model waits through mid-sentence pauses but runs against a remote endpoint that
    can hang (observed: turns never closing, so on_user_turn_completed never fired,
    so nothing was spoken) AND it adds latency before a Tier-2 answer even starts.
    Opt into it with TURN_DETECTION=multilingual once that path is reliable.
    """
    mode = (cfg.turn_detection or "stt").lower()
    if mode == "multilingual":
        if _MultilingualModel is None:
            log.warning("turn_detector_unavailable", extra={"vigil": {"fallback": "stt"}})
            return "stt"
        try:
            return _MultilingualModel()
        except Exception as exc:  # noqa: BLE001
            log.warning("turn_detector_unavailable", extra={"vigil": {"error": repr(exc), "fallback": "stt"}})
            return "stt"
    return mode if mode in ("stt", "vad", "manual") else "stt"


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
        # Wake state machine (see vigil.core.dialog for the pure decision):
        # `_armed_until` is the deadline of the sticky listening window opened by
        # the wake word; `_buffer` accumulates the query across the (possibly
        # split) turns within it. This is what makes "Vigil" <pause> "how much
        # epi" work as one query and stops a bare "Vigil" from blurting a miss.
        self._buffer = ""
        self._armed_until = 0.0

    def _disarm(self) -> None:
        """Close the listening window and clear the buffer (require a fresh wake
        word before the next answer)."""
        self._armed_until = 0.0
        self._buffer = ""

    async def _speak(self, answer) -> None:  # noqa: ANN001
        await LiveKitSpeaker(self.session).say(answer.spoken_form)
        try:
            await self._channel.publish_card(answer.card)
        except Exception as exc:  # noqa: BLE001 - a card failure must never block the dose
            log.warning("card_publish_failed", extra={"vigil": {"error": repr(exc)}})

    async def _route_and_speak(self, query: str) -> None:
        """Run the pure pipeline on `query` and speak the result. Updates the
        pending-clarification / window state from the answer."""
        loop = asyncio.get_running_loop()
        work = functools.partial(
            handle_transcript,
            f"vigil {query}",  # re-inject the wake token for the pure pipeline
            index=self._index,
            synthesizer=self._synthesizer,
            logger=log,
            tier2_alpha=self._cfg.tier2_alpha,
            tier2_top_k=self._cfg.tier2_top_k,
            provider_role=self._cfg.provider_role,
        )
        answer = await loop.run_in_executor(None, work)

        if answer is not None:
            action = (
                "clarify" if answer.clarification is not None
                else "answer" if answer.found
                else "fallback"
            )
            log.info("routing", extra={"vigil": {
                "query": query,
                "tier": answer.tier.value,
                "action": action,
                "spoken": answer.spoken_form[:160],
            }})

        self._buffer = ""  # this query is consumed either way
        if answer is not None and answer.clarification is not None:
            # Asked a clarifying question -> hold it until the medic replies. The
            # pending clarification is NOT tied to the wake-window timer (a long
            # multi-option question can take longer to speak than the window),
            # so it persists until a reply resolves it or a fresh drug query
            # abandons it. The window is closed; the reply path doesn't need it.
            self._pending = answer.clarification
            self._armed_until = 0.0
        else:
            # Answered (dose / Tier-2 / safe fallback) -> require a fresh wake word.
            self._disarm()
        if answer is not None:
            await self._speak(answer)

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:  # noqa: ANN001
        transcript = (new_message.text_content or "").strip()
        if not transcript:
            raise StopResponse()

        now = time.monotonic()
        window = self._cfg.wake_window_seconds

        # --- Mid-clarification: resolve the medic's reply ----------------------
        # A pending clarification persists until answered (it does NOT expire with
        # the wake window -- a 3-option question can take >window seconds to speak
        # and hear back). The wake word is OPTIONAL in the reply ("Vigil, stable
        # VT"). The reply is a bare indication that names NO drug; a turn that
        # NAMES a drug is a fresh question -> abandon the clarification and route
        # it (this is the "stale clarification swallowed my next query" fix).
        if self._pending is not None:
            reply = wake.strip_wake(transcript).strip()
            if not reply:
                raise StopResponse()  # bare "Vigil" -- keep waiting for the reply
            if not dialog.turn_is_fresh_query(reply):
                pending = self._pending
                self._pending = None  # one-shot: resolve exactly once
                self._disarm()
                work = functools.partial(
                    resolve_clarification,
                    reply,
                    clarification=pending,
                    provider_role=self._cfg.provider_role,
                    logger=log,
                )
                loop = asyncio.get_running_loop()
                answer = await loop.run_in_executor(None, work)
                log.info("routing", extra={"vigil": {
                    "query": reply,
                    "tier": "tier1_clarify_reply",
                    "action": "answer" if answer.found else "fallback",
                    "spoken": answer.spoken_form[:160],
                }})
                await self._speak(answer)
                raise StopResponse()
            # Names a drug -> a fresh question. Abandon the clarification and route
            # this turn now (regardless of wake word / window state).
            self._pending = None
            self._buffer = reply
            self._armed_until = now + window
            await self._route_and_speak(self._buffer)
            raise StopResponse()

        # --- Wake gating with a sticky listening window -----------------------
        triggered = wake.detect_wake(transcript)
        in_window = now < self._armed_until
        if not triggered and not in_window:
            # Reactive only: ignore untriggered background / side-conversation.
            raise StopResponse()

        if triggered:
            # Fresh wake word -> (re)start the buffer from the post-wake text.
            self._buffer = wake.strip_wake(transcript).strip()
        else:
            # In-window continuation: the wake word and query split across turns.
            self._buffer = f"{self._buffer} {transcript}".strip()
        self._armed_until = now + window

        # --- Answer now, or keep listening? -----------------------------------
        if not dialog.query_has_substance(self._buffer):
            # Still forming ("vigil", "vigil what") -> stay silent, keep the
            # window armed for the next fragment. No spurious "Not in protocol".
            log.info("turn", extra={"vigil": {"state": "listening", "buffer": self._buffer}})
            raise StopResponse()

        await self._route_and_speak(self._buffer)
        # No LLM is configured; stop here so the session doesn't attempt a reply.
        raise StopResponse()


async def entrypoint(ctx: JobContext) -> None:
    configure_logging()
    cfg = load_config()
    index = build_index(cfg)
    synthesizer = build_synthesizer(cfg)

    session_kwargs = {
        # Deepgram `endpointing` (ms of silence before utterance-final) raised
        # from the ~25ms default so STT doesn't slam the turn shut the instant the
        # medic pauses after "Vigil" -- fewer wake/query splits, fewer "flushing
        # vad" warnings. The wake window backstops any split that still slips
        # through. Provider-specific (Deepgram); harmless if the model ignores it.
        "stt": inference.STT(
            cfg.stt_model,
            language=cfg.stt_language,
            extra_kwargs={"endpointing": cfg.stt_endpointing_ms},
        ),
        "tts": build_tts(cfg),
        # No llm= on purpose: the session never auto-replies; we drive all speech.
        # Direct kwargs (1.5.x): which detector ends a turn + the wait bounds before
        # the turn closes. min keeps a quick finish snappy; max caps a mid-query
        # pause so it isn't cut into fragments.
        "turn_detection": _build_turn_detection(cfg),
        "min_endpointing_delay": cfg.min_endpointing_delay,
        "max_endpointing_delay": cfg.turn_max_delay,
    }
    if (vad := _build_vad()) is not None:
        session_kwargs["vad"] = vad

    session = AgentSession(**session_kwargs)
    channel = LiveKitChannel(ctx.room)
    agent = VigilAgent(cfg=cfg, index=index, synthesizer=synthesizer, channel=channel)

    # Clean Moss shutdown: unload + stop the loop thread before the worker tears
    # down, else the native core can abort ("mutex lock failed") at process exit.
    if hasattr(index, "close"):
        async def _close_index():
            index.close()
        ctx.add_shutdown_callback(_close_index)

    await session.start(
        agent=agent,
        room=ctx.room,
        # TODO: add noise_cancellation + RoomInputOptions tuning after the live run
        # confirms the installed plugin's API shape.
    )

    # Greet on start so the medic hears the agent is live and the TTS path is
    # confirmed working (set STARTUP_GREETING="" to disable).
    if cfg.startup_greeting:
        await session.say(cfg.startup_greeting)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
