# Vigil — Agent / Server

The Python LiveKit agent: detects the wake word "Vigil", routes the query, and answers.
- **Tier 1 (dose):** deterministic, **no LLM** — the exact protocol dose is spoken verbatim.
- **Tier 2 (synthesis):** Minimax LLM constrained to retrieved chunks, with PII redaction and a
  number-grounding guard that discards any invented number.

The dose path is structurally LLM-free — `vigil/core/` imports nothing external, enforced by
`tests/test_core_purity.py`. See `CLAUDE.md` in this directory for the full contract.

## Setup

System Python is 3.14, which `livekit-agents` does not support. Use pyenv 3.12.9 (the `.venv`
here was created from it). Secrets go in `agent/.env` (gitignored) — copy `.env.example`:

```bash
cd agent
# venv already created from /Users/nikhilyachareni/.pyenv/versions/3.12.9/bin/python
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env   # fill in keys (see "Credentials" below)
```

## Test (this is how you verify end-to-end as you go)

```bash
# Hermetic gate — no network, no creds. The 100% Tier-1 gate + Tier-2 + grounding + purity.
.venv/bin/python -m pytest tests -v

# Opt-in LIVE integration (frugal — a couple of tiny capped Minimax calls). Reads .env.
RUN_INTEGRATION=1 .venv/bin/python -m pytest tests/integration -v
```

The hermetic suite is the default gate and hits nothing external (fast, free, deterministic).
Integration tests self-skip unless `RUN_INTEGRATION=1` and `MINIMAX_API_KEY` is set — so you can
confirm the real Minimax path on demand without burning credits.

## Live mic↔speaker loop (no phone)

```bash
.venv/bin/python agent.py console
```

Creds are set and verified (worker registers with LiveKit Cloud; Minimax LLM + TTS confirmed).
Speak "Vigil, what's the adult epi dose for anaphylaxis" (Tier-1, verbatim) or "Vigil, what
should I consider before giving epinephrine?" (Tier-2, grounded synthesis). First run downloads
the silero VAD + turn-detector models (a few hundred MB).

## Serve a real room for the app

`console` is a local-only mic loop and does **not** serve real LiveKit rooms. To let the app
(or the Agents Playground) join, run the worker in `dev` mode — it registers with LiveKit Cloud
and, with automatic dispatch (no `agent_name`), auto-joins whatever room the client creates:

```bash
.venv/bin/python agent.py dev        # agent worker -> joins the client's room on demand
```

The app joins via a **token**, not by connecting to this agent. Run the tiny token endpoint
(no extra deps — aiohttp + livekit.api ship with livekit-agents); it mints a JWT for room
`vigil-demo` from the same `LIVEKIT_*` creds:

```bash
.venv/bin/python token_server.py     # GET :8080/token?identity=medic -> { serverUrl, ... }
```

The agent dials out (no inbound port); the token endpoint is the only thing the app must reach
(laptop LAN IP / `ngrok http 8080` / LiveKit Sandbox). Full client contract: see `INTEGRATION.md`.

## Credentials (in `agent/.env`)

| Key | Purpose | Status |
|---|---|---|
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` / `LIVEKIT_PROJECT_ID` | transport + inference STT/TTS | set, **verified** (worker registers) |
| `MINIMAX_API_KEY` | Tier-2 LLM + Minimax TTS | set, **verified** |
| `MINIMAX_TTS_BASE_URL` | bare host `https://api.minimax.io` (NOT the LLM `.../v1`) | set |
| `MINIMAX_GROUP_ID` | not needed (Minimax TTS works without it) | optional |
| `MOSS_PROJECT_ID` / `MOSS_PROJECT_KEY` | real retrieval (not wired this round) | stored for later |

## Layout

```
vigil/core/      pure logic (no external imports — dose path) incl. prompt + grounding
vigil/ports/     interfaces (RetrievalIndex, Speaker, CardChannel, Synthesizer)
vigil/adapters/  FakeIndex, MossIndex (stub), LiveKit speaker/channel, MinimaxSynthesizer
vigil/config.py  env + model IDs
agent.py         LiveKit worker entrypoint
data/            protocols_gold.json  (placeholder doses — verify vs protocol PDF)
tests/           hermetic E2E + unit ; tests/integration/ (opt-in, live)
```
