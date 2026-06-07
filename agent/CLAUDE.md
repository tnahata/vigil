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
- **dotenv-timing gotcha (fixed in code):** `agent.py` calls `load_dotenv()` at **import time**
  (anchored to its own dir), not just inside `load_config()`. In `console`/`dev` mode the LiveKit
  CLI checks `LIVEKIT_URL` at worker startup *before* `entrypoint()` runs, so a late load raised
  `ValueError: ws_url is required` even with a correct `.env`. Keep the import-time load.
- **Deferred:** real `MossIndex` (FakeIndex is the default; Moss creds stored for later), the async
  Moss bridge, noise-cancellation/RoomInputOptions tuning, the `/app` RN client, real-device testing.
