# CLAUDE.md — Vigil `/agent` (Python server)

Server-side brain for Vigil. See the repo-root `CLAUDE.md` for product framing and the
defended claim. This file is the contract for working *inside* `agent/`.

## The one rule: the dose path is structurally LLM-free

`vigil/core/` is **pure**. It MUST NOT import `livekit`, `openai`, `minimax`, `moss`/
`inferedge_moss`, or `dotenv`. Enforced by `tests/test_core_purity.py` (an AST scan). That
test *is* the defended claim: if it fails, a model can reach the dose path.

**Tier-1 safety invariant:** a Tier-1 answer's `spoken_form` and `dose` are copied *verbatim*
from the retrieved `Doc` — never assembled from a number in code, never model-produced.

**Tier-2 safety (defense-in-depth):** Tier 2 *does* use an LLM (Minimax), but (a) PII is
redacted from the query first, (b) the prompt forbids any number not in the excerpts, and
(c) a **number-grounding guard** (`core/grounding.py`) discards any answer that introduces a
number absent from the retrieved chunks. On any miss/failure either tier returns the fixed
fallback ("Not in protocol. Contact medical control."), never a guess, never a crash.

## Architecture (hexagonal)

```
vigil/core/      pure logic — models, aliases, wake, router, pipeline, errors, trace,
                 redact, prompt (Tier-2 constrained prompt), grounding (number guard)
vigil/ports/     interfaces: RetrievalIndex, Speaker, CardChannel, Synthesizer
vigil/adapters/  FakeIndex, MossIndex (stub), LiveKitSpeaker/Channel, MinimaxSynthesizer, logging
vigil/config.py  env + model IDs (kept out of core)
agent.py         LiveKit worker — the only place real LiveKit/Minimax-TTS are wired
token_server.py  tiny aiohttp /token endpoint (signs room JWTs; NOT on the dose path)
data/            protocols_gold.json (FakeIndex seed AND the gold test set)
tests/           hermetic E2E + unit (the gate) ; tests/integration/ (opt-in, live)
```

**Tier-1 flow:** `handle_transcript(t, index=...)` → wake → route → **alias-normalize (before
retrieval)** → `index.query(alpha=0, $eq drug+population)` → verbatim `Answer`.

**Tier-2 flow:** route→Tier2 → hybrid retrieve (`alpha≈0.6`, population filter) → redact PII →
constrained prompt → `synthesizer.synthesize()` → grounding guard → `Answer` (or safe fallback).
`handle_transcript(..., synthesizer=None)` ⇒ Tier 2 degrades to the safe fallback (the hermetic
default).

**Worker:** `AgentSession` is built with **no `llm=`**, so it never auto-replies — every spoken
line is an explicit `session.say()` (bypasses the LLM). We react in `VigilAgent.on_user_turn_completed`
(NOT per raw STT final): the turn-detector model aggregates the whole utterance across natural
pauses, so "Vigil … epi dose for anaphylaxis" arrives as one transcript instead of fragments that
each miss the wake word. That hook still fires with no LLM (turn detection runs independently); we
run the pipeline, `say()` the answer, publish the card, then raise `StopResponse`. The sync pipeline
runs in a thread executor so a multi-second Tier-2 LLM call never blocks audio; Tier 1 stays sub-ms.

**Plugin registration gotcha (load-bearing):** LiveKit plugins (`silero`, `turn_detector`, `minimax`)
call `register_plugin()`/`register_runner()` at **import time**, which *must* run on the main thread.
So `agent.py` imports them at module top-level, NOT lazily inside `entrypoint()` (which runs on the
job-runner thread → `RuntimeError: ... must be registered on the main thread`, then silent fallback
to no-VAD/no-turn-detector/Cartesia-TTS). The `.load()`/`()` model *constructors* are fine on the
worker thread, but `MultilingualModel()` needs a live job context, so it's built inside `entrypoint`.

## How to extend

- **Add a protocol/dose:** add to `data/protocols_gold.json` (`dose_value` + hand-written
  `spoken_form` with number-words + `protocol_id`) and a gold query in
  `tests/test_pipeline_tier1_gold.py`. Doses there are PLACEHOLDERS — verify vs the source PDF.
- **Add a drug alias:** edit `_CANONICAL_TO_ALIASES` in `vigil/core/aliases.py`.
- **Swap retrieval / synthesis:** implement the `RetrievalIndex` / `Synthesizer` port; wire it in
  `build_index()` / `build_synthesizer()` in `agent.py`. Keep `core` unaware of the backend.
- **Never** put a model call, network call, or LiveKit/openai import in `vigil/core/`.

## Environment & secrets

System Python 3.14 is incompatible with `livekit-agents` — use **pyenv 3.12.9** (`.venv` is
already created from it). Secrets live ONLY in `agent/.env` (gitignored; `.gitignore` blocks
`.env*`, `*.key`, `*.pem`, `.moss/`). Never commit `.env`. All model IDs are env-driven.

```
# already done: venv from 3.12.9
.venv/bin/python -m pip install -r requirements.txt   # livekit + minimax + openai + plugins
```

## Run / test

```
# 1) Hermetic gate (no network/creds) — Tier-1 100% gate + Tier-2 + grounding + purity:
.venv/bin/python -m pytest tests -v

# 2) Opt-in live integration (frugal: a couple of small capped Minimax calls):
RUN_INTEGRATION=1 .venv/bin/python -m pytest tests/integration -v
#    self-skips unless RUN_INTEGRATION=1 + MINIMAX_API_KEY present (loaded from .env)

# 3) Live mic<->speaker loop (no phone). Creds are in .env; run from agent/:
.venv/bin/python agent.py console

# 4) Serve a REAL room for the app (console does NOT). `dev` registers the worker and,
#    with automatic dispatch (no agent_name), auto-joins the client's room:
.venv/bin/python agent.py dev
#    The app joins via a token, not by reaching this agent. token_server.py mints a JWT
#    for room `vigil-demo` (aiohttp + livekit.api, both already installed). Client contract
#    is in INTEGRATION.md. The agent dials out (no inbound port); the token endpoint is the
#    only thing the app must reach (laptop LAN IP / ngrok / LiveKit Sandbox).
.venv/bin/python token_server.py     # GET :8080/token?identity=medic
```

Credit hygiene: hermetic tests hit nothing external and are the default gate. Integration tests
only run when you opt in, and are intentionally tiny. Don't add live calls to the default suite.

## Status / verified

- **Verified live:** Minimax LLM (Tier 2, OpenAI-compatible) + the grounding guard against the
  real model; Minimax TTS voice-out (no Group ID needed); LiveKit creds authenticate and the
  agent worker registers with LiveKit Cloud (`AW_…`). Hermetic gate (32) + opt-in integration green.
- **Verified startup:** `console` mode builds the AgentSession with silero VAD + multilingual
  turn detector + Minimax TTS all constructed (no main-thread/`_unavailable` warnings, no
  deprecation warning) and reaches `session.start()`. Model files pre-downloaded via
  `python agent.py download-files`. (The full spoken round-trip still needs a human at a mic.)
- **Ready to run (needs a human at a mic):** `python agent.py console` — the interactive voice loop.
- **TTS gotcha (fixed in code):** `MINIMAX_TTS_BASE_URL` must be the bare host
  (`https://api.minimax.io`) — the plugin appends `/v1/t2a_v2`. Do NOT reuse `MINIMAX_BASE_URL`
  (which is `.../v1` for the LLM) or TTS 404s with a doubled `/v1`.
- **TTS PCM gotcha (fixed in code):** Minimax TTS runs with `audio_format="pcm"` (`MINIMAX_TTS_FORMAT`).
  PCM hits LiveKit's raw-sample path and skips the PyAV decoder; the default **MP3** is streamed as
  hex over the Minimax WebSocket and intermittently dies with `av.error.InvalidDataError` / "I/O
  operation on closed file". Don't switch TTS back to mp3 without re-testing the live audio path.
- **Turn endpointing (live-fixed):** default `TURN_DETECTION=stt` — the turn ends on Deepgram's
  final transcript (prompt + reliable). The `multilingual` EOU model was observed to never close
  turns in console mode (it only predicted at shutdown, so `on_user_turn_completed` never fired and
  nothing was spoken) and it adds latency before a Tier-2 answer starts — it's opt-in now. Endpointing
  bounds are passed as the direct `min_endpointing_delay`/`max_endpointing_delay` kwargs (NOT the
  `turn_handling` dict); `TURN_MAX_DELAY` (now 3.0s) is the hard cap. A startup greeting
  (`STARTUP_GREETING`) is spoken on `session.start()` to confirm the TTS path live.
- **Wake state machine (live-fixed — the "time it perfectly" flakiness):** STT endpointing splits
  the wake word from the question into separate turns ("Vigil" <pause> "how much epi"), so the wake
  turn was empty (→ spurious "Not in protocol") and the query turn missed the wake word (→ dropped).
  Fix: `VigilAgent` keeps a **sticky listening window** (`WAKE_WINDOW_SECONDS`, default 8s) opened by
  "Vigil"; turns within it CONTINUE the buffered query without repeating the wake word, and the
  stitched buffer is re-routed each turn. The pure gate `core/dialog.query_has_substance` (intent OR a
  known drug) decides *answer now vs. keep listening*, so bare "Vigil"/half-formed turns stay silent
  instead of blurting a miss — while "how much rocuronium" still reports "not in protocol" (intent
  present). STT is also relaxed (`MIN_ENDPOINTING_DELAY=0.8`, Deepgram `STT_ENDPOINTING_MS=200`) so
  fewer turns split at the source and the cosmetic `flushing vad` warning quiets down. VAD stays on
  (interruption handling); the warning never dropped audio/text.
- **Clarification reply robustness (live-fixed):** a pending clarification **persists until answered**
  — it is NOT tied to the wake-window timer (a 3-option question can take longer to speak + hear back
  than the window; tying them dropped the reply). The next turn is the REPLY iff it names no drug
  (`dialog.turn_is_fresh_query`): a bare indication ("stable VT", with or without the wake word) is
  the reply; a turn that NAMES a drug ("what dosage of atropine") is a fresh question that abandons the
  clarification and routes anew — so a stale clarification can't swallow the next query. `core/disambig`
  scores only the indications' DISTINGUISHING tokens (tokens shared by every candidate, e.g. "VT", are
  excluded) and falls back to an ordinal/cardinal position word ("the first one" / "number two") when
  STT mangles the symptom word ("stable VT" → "Abel VT"). An ambiguous/whiffed reply still
  safe-falls-back — never guesses a dose.
- **Tier-2 routing precedence + breadth (live-fixed):** two routing bugs seen live. (1) "what dosage
  of atropine **should I give**" was hijacked to Tier-2 because `should i give` was a Tier-2 cue matched
  FIRST → the LLM answered "Based on unstable bradycardia…". (2) "**should I use** atropine **if** the
  patient has an MI" (a judgment question) fell through to Tier-1 and asked a pointless dose
  clarification. Fix in `router.classify`: an explicit dose **noun** (`dose(s)`/`dosage(s)`/`how much`/
  `mg`/… — note the plurals) + a drug is checked BEFORE Tier-2 and wins outright, so a dose question is
  never diverted to the LLM regardless of phrasing; dose **verbs** (`give/push/administer`) are weaker
  and do NOT outrank a judgment cue. Tier-2 cues broadened (consider / precaution / side effect /
  adverse / risk / `should i (give|use|administer|push)` / "what should I know" / "tell me about") so
  judgment questions reach synthesis. Guarded by `test_dose_question_with_should_i_give_stays_tier1`,
  `test_should_i_use_judgment_routes_tier2`, and `test_dose_queries_never_diverted_to_tier2`.
- **Tier-2 model (live-fixed):** `MINIMAX_LLM_MODEL=MiniMax-Text-01` (non-reasoning). MiniMax-M3 is a
  reasoning model: 5–25s and sometimes returns nothing (whole token budget spent inside `<think>`).
  Text-01 answers the same constrained-RAG query in ~1.5s. The prompt forces ONE ≤25-word sentence,
  answer-only-what-was-asked, and no spoken citations (the card still carries them). `_strip_reasoning`
  in the synthesizer stays as a safety net if a reasoning model is ever reselected.
- **dotenv-timing gotcha (fixed in code):** `agent.py` calls `load_dotenv()` at **import time**
  (anchored to its own dir), not just inside `load_config()`. In `console`/`dev` mode the LiveKit
  CLI checks `LIVEKIT_URL` at worker startup *before* `entrypoint()` runs, so a late load raised
  `ValueError: ws_url is required` even with a correct `.env`. Keep the import-time load.
- **Moss retrieval WIRED & verified live:** the agent queries the real in-process index
  `vigil-protocol` (88 chunks, 26 drugs, built by `moss-test/create_index.py` from
  `data/chunks.json`) when `RETRIEVAL_BACKEND=moss`. `MossIndex` (`adapters/moss_index.py`) bridges
  Moss's async client to the sync port via a persistent client + a daemon event-loop thread:
  `load_index` once (~1.4 s), then in-process queries at **3–6 ms**. Shutdown is clean (the loop
  thread is joined at `atexit` — without it the native core aborts with "mutex lock failed").
  `Doc.from_chunk` is the single chunk→Doc mapping (`patient_type→population`,
  `value_machine→dose_value`, `value_spoken→spoken_form`, `source+page→citation`), used by BOTH
  `MossIndex` and the chunks-seeded `FakeIndex`, so the hermetic gate exercises the real schema.
- **Hermetic gate vs Moss ranking — don't conflate:** `pytest tests` (40, green) proves
  routing + alias + schema plumbing + verbatim-copy + grounding + purity, but the FakeIndex keyword
  scorer does NOT replicate Moss BM25. Moss's ordering is validated only by the opt-in
  `RUN_MOSS=1 pytest tests/integration/test_moss_parity.py` (green).
- **Tier-1 multi-dose disambiguation (`core/disambig.py`):** 16 (drug, population) pairs have >1 dose
  separated only by indication (atropine adult: bradycardia 1 mg vs organophosphate 2 mg). Tier-1
  now retrieves `top_k=5` and either resolves by indication or asks ONE clarifying question (named
  indications, never a dose number); the reply is resolved once (never re-asked). The full
  transcript is sent to Moss (the reference `moss-test/query.py` queries by drug name only and so
  returns the wrong indication's dose — fixed here). Cross-turn pending state lives on `VigilAgent`.
- **Role gating (`core/roles.py`):** Tier-1 doses are gated by `provider_role` (from the auth
  profile; `PROVIDER_ROLE`, default `PARAMEDIC`). Authorized → dose verbatim; conditional → dose +
  caveat; not-authorized → withholds the number. The dose number is never altered.
- **Known gaps (don't overclaim):** 6 dose chunks have empty `value_spoken` (ketamine/aspirin/
  buprenorphine/nitroglycerin peds, sodium-bicarb adult) → safe fallback, no guess. Concentration
  collision: bare "epi" → `EPINEPHRINE (1:1,000)` (anaphylaxis), not the `1:10,000` cardiac dose.
- **Deferred:** noise-cancellation/RoomInputOptions tuning, the `/app` RN client, real-device testing.
