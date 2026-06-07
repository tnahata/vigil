"""Config / env loading. Kept OUT of vigil.core (which must stay dep-free).

All model IDs live here / in .env -- never hard-coded in logic -- because some
provider model IDs from docs may be wrong and must stay swappable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # python-dotenv is optional for the pure tests
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_GOLD = os.path.join(os.path.dirname(_PKG_DIR), "data", "protocols_gold.json")
_DEFAULT_CHUNKS = os.path.join(os.path.dirname(_PKG_DIR), "data", "chunks.json")


@dataclass(frozen=True)
class Config:
    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_project_id: str = ""

    # STT
    stt_model: str = "deepgram/nova-3"
    stt_language: str = "multi"

    # TTS (provider-selectable; minimax falls back to inference if unavailable)
    tts_provider: str = "minimax"          # "minimax" | "inference"
    minimax_tts_model: str = "speech-2.8-hd"
    minimax_tts_voice: str = "English_expressive_narrator"
    # Raw PCM bypasses the PyAV MP3 decoder in LiveKit's AudioEmitter -- MP3 streaming
    # over the Minimax WebSocket intermittently fails to decode ("Invalid data found").
    minimax_tts_format: str = "pcm"        # "pcm" | "mp3" | "flac" | "wav"
    minimax_tts_speed: float = 1.25        # playback speed multiplier; plugin range [0.5, 2.0]
    # TTS base host WITHOUT a path -- the plugin appends /v1/t2a_v2 itself. Must NOT
    # carry a trailing /v1 (that's only for the OpenAI-compatible LLM base url).
    minimax_tts_base_url: str = "https://api.minimax.io"
    minimax_group_id: str = ""
    inference_tts_model: str = "cartesia/sonic-2"

    # Minimax LLM (Tier 2)
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    # Tier-2 LLM. A NON-reasoning model on purpose: MiniMax-M3 (reasoning) spends
    # its whole budget "thinking" -- 5-25s and sometimes no answer at all. Text-01
    # answers the same constrained-RAG query in ~1.5s, concise and reliable.
    minimax_llm_model: str = "MiniMax-Text-01"

    # Tier-2 retrieval tuning. top_k=3 keeps the LLM context tight (fewer chunks ->
    # less to ramble over + faster); raise it only if recall is the bottleneck.
    tier2_alpha: float = 0.6
    tier2_top_k: int = 3

    # Turn-taking. `turn_detection` decides when a user turn ends:
    #   "stt"  -> end on the STT provider's (Deepgram) final -- deterministic and
    #            reliable; the default. "vad" -> end on VAD silence. "multilingual"
    #            -> the EOU model (waits through mid-sentence pauses but depends on a
    #            remote endpoint and can hang -- opt in only). "manual".
    # min/max endpointing delay bound how long to wait for more speech before
    # closing the turn (max bumped above 3.0s so a mid-query pause isn't cut into
    # fragments; the EOU/STT logic still ends fast on a confident finish).
    turn_detection: str = "stt"
    # Bumped 0.5 -> 0.8: with STT endpointing, the wake word + question were
    # splitting into separate turns on a brief pause ("Vigil" <pause> "how much
    # epi"). A slightly longer wait keeps them in one turn more often. The wake
    # window (below) backstops any split that still happens.
    min_endpointing_delay: float = 0.8
    turn_max_delay: float = 6.0  # == max_endpointing_delay
    # Deepgram silence (ms) before it declares utterance-final. Default is ~25ms,
    # which closes turns very eagerly (and spams the "flushing vad" warning).
    # Raising it lets STT wait a beat for the medic to keep talking.
    stt_endpointing_ms: int = 200

    # Sticky listening window (seconds) after the wake word "Vigil". Within it,
    # turns are treated as the continuing query even WITHOUT repeating the wake
    # word -- so a wake/question split across turns is stitched back together, and
    # a clarification reply doesn't need (but may include) the wake word. Reactive
    # only: nothing is retrieved/spoken on untriggered speech outside the window.
    wake_window_seconds: float = 8.0

    # Spoken on session start so the medic hears the agent is live (also confirms
    # the TTS audio path). Set STARTUP_GREETING="" to disable.
    startup_greeting: str = "Vigil online. Say Vigil, then your question."

    # Retrieval backend
    retrieval_backend: str = "fake"        # "fake" | "moss"
    moss_index_name: str = "vigil-protocol"
    moss_project_id: str = ""
    moss_project_key: str = ""

    # Provider role for Tier-1 authorization gating. Sourced from the user's auth
    # profile in production; defaults to PARAMEDIC for the demo (no hands-free
    # role declaration). One of EMT | AEMT | PARAMEDIC.
    provider_role: str = "PARAMEDIC"

    gold_data_path: str = _DEFAULT_GOLD
    chunks_data_path: str = _DEFAULT_CHUNKS  # real protocol chunks (FakeIndex seed)
    run_integration: bool = False


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def load_config() -> Config:
    load_dotenv()
    return Config(
        livekit_url=os.getenv("LIVEKIT_URL", ""),
        livekit_api_key=os.getenv("LIVEKIT_API_KEY", ""),
        livekit_api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
        livekit_project_id=os.getenv("LIVEKIT_PROJECT_ID", ""),
        stt_model=os.getenv("STT_MODEL", "deepgram/nova-3"),
        stt_language=os.getenv("STT_LANGUAGE", "multi"),
        tts_provider=os.getenv("TTS_PROVIDER", "minimax"),
        minimax_tts_model=os.getenv("MINIMAX_TTS_MODEL", "speech-2.8-hd"),
        minimax_tts_voice=os.getenv("MINIMAX_TTS_VOICE", "English_expressive_narrator"),
        minimax_tts_format=os.getenv("MINIMAX_TTS_FORMAT", "pcm"),
        minimax_tts_speed=float(os.getenv("MINIMAX_TTS_SPEED", "1.25")),
        minimax_tts_base_url=os.getenv("MINIMAX_TTS_BASE_URL", "https://api.minimax.io"),
        minimax_group_id=os.getenv("MINIMAX_GROUP_ID", ""),
        inference_tts_model=os.getenv("INFERENCE_TTS_MODEL", "cartesia/sonic-2"),
        minimax_api_key=os.getenv("MINIMAX_API_KEY", ""),
        minimax_base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
        minimax_llm_model=os.getenv("MINIMAX_LLM_MODEL", "MiniMax-M3"),
        tier2_alpha=_f("TIER2_ALPHA", 0.6),
        tier2_top_k=_i("TIER2_TOP_K", 3),
        turn_detection=os.getenv("TURN_DETECTION", "stt"),
        min_endpointing_delay=_f("MIN_ENDPOINTING_DELAY", 0.8),
        turn_max_delay=_f("TURN_MAX_DELAY", 6.0),
        stt_endpointing_ms=_i("STT_ENDPOINTING_MS", 200),
        wake_window_seconds=_f("WAKE_WINDOW_SECONDS", 8.0),
        startup_greeting=os.getenv("STARTUP_GREETING", "Vigil online. Say Vigil, then your question."),
        retrieval_backend=os.getenv("RETRIEVAL_BACKEND", "fake"),
        moss_index_name=os.getenv("MOSS_INDEX_NAME", "vigil-protocol"),
        moss_project_id=os.getenv("MOSS_PROJECT_ID", ""),
        moss_project_key=os.getenv("MOSS_PROJECT_KEY", ""),
        provider_role=os.getenv("PROVIDER_ROLE", "PARAMEDIC"),
        gold_data_path=os.getenv("VIGIL_GOLD_PATH", _DEFAULT_GOLD),
        chunks_data_path=os.getenv("VIGIL_CHUNKS_PATH", _DEFAULT_CHUNKS),
        run_integration=os.getenv("RUN_INTEGRATION", "") == "1",
    )
