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
    # TTS base host WITHOUT a path -- the plugin appends /v1/t2a_v2 itself. Must NOT
    # carry a trailing /v1 (that's only for the OpenAI-compatible LLM base url).
    minimax_tts_base_url: str = "https://api.minimax.io"
    minimax_group_id: str = ""
    inference_tts_model: str = "cartesia/sonic-2"

    # Minimax LLM (Tier 2)
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_llm_model: str = "MiniMax-M3"

    # Tier-2 retrieval tuning
    tier2_alpha: float = 0.6
    tier2_top_k: int = 4

    # Turn-taking: how long to wait for more speech before forcing the turn closed.
    # The EOU model decides end-of-turn; this is the hard cap when it keeps saying
    # "not done". Bumped above the 3.0s default so a medic's mid-query pause
    # ("Vigil, what's the... uh... peds epi dose") isn't cut into fragments.
    turn_max_delay: float = 6.0

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
        minimax_tts_base_url=os.getenv("MINIMAX_TTS_BASE_URL", "https://api.minimax.io"),
        minimax_group_id=os.getenv("MINIMAX_GROUP_ID", ""),
        inference_tts_model=os.getenv("INFERENCE_TTS_MODEL", "cartesia/sonic-2"),
        minimax_api_key=os.getenv("MINIMAX_API_KEY", ""),
        minimax_base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
        minimax_llm_model=os.getenv("MINIMAX_LLM_MODEL", "MiniMax-M3"),
        tier2_alpha=_f("TIER2_ALPHA", 0.6),
        tier2_top_k=_i("TIER2_TOP_K", 4),
        turn_max_delay=_f("TURN_MAX_DELAY", 6.0),
        retrieval_backend=os.getenv("RETRIEVAL_BACKEND", "fake"),
        moss_index_name=os.getenv("MOSS_INDEX_NAME", "vigil-protocol"),
        moss_project_id=os.getenv("MOSS_PROJECT_ID", ""),
        moss_project_key=os.getenv("MOSS_PROJECT_KEY", ""),
        provider_role=os.getenv("PROVIDER_ROLE", "PARAMEDIC"),
        gold_data_path=os.getenv("VIGIL_GOLD_PATH", _DEFAULT_GOLD),
        chunks_data_path=os.getenv("VIGIL_CHUNKS_PATH", _DEFAULT_CHUNKS),
        run_integration=os.getenv("RUN_INTEGRATION", "") == "1",
    )
