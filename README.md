# Vigil — Offline EMT Dosage Lookup Spike

Proof-of-concept for a fully offline, voice-queryable drug dosage reference for Tier-1 EMTs. The core question: can a browser embed a semantic index locally so that queries never hit the network after initial setup?

This branch contains two independent experiments:

---

## `unsiloed-test/` — PDF Ingestion Pipeline (Python)

Converts a structured EMS protocol PDF into Moss-ready documents.

**Stage 1 — Parse:** `parse_pdf.py` sends the PDF to the Unsiloed API and caches the structured JSON output in `parsed_output.json`. Subsequent runs are cache-first (no API credits consumed if the cache exists).

**Stage 2 — Chunk:** `chunk.py` reads `parsed_output.json` and produces `chunks.json` — a flat list of documents, one per dose statement, ready to be ingested by Moss.

### Setup

```bash
cd unsiloed-test
pip install -r requirements.txt
```

You'll need an Unsiloed API key set in your environment to run Stage 1. If `parsed_output.json` already exists, Stage 1 is skipped automatically.

### Run

```bash
python3 parse_pdf.py          # Stage 1 — calls Unsiloed API, writes parsed_output.json
python3 chunk.py              # Stage 2 — reads parsed_output.json, writes chunks.json (dev: 2 drugs)
python3 chunk.py --all        # Stage 2 — full 26-drug run
```

Stage 1 is cache-first: if `parsed_output.json` already exists with a `Succeeded` result, the API is never called again. Run Stage 1 once, then iterate on Stage 2 freely.

---

## `moss-test/` — Browser Offline Demo (TypeScript + Vite)

Demonstrates zero-network semantic search in the browser using the Moss SDK.

**Warm-up (online):** pushes 5 hardcoded EMT drug docs to Moss Cloud for server-side embedding, then downloads the index into browser memory via `loadIndex()`.

**Query (offline):** each query is embedded locally by Moss's WASM model and searched against the in-memory index — no network calls after warm-up.

**Network proof:** `fetch`, `XMLHttpRequest`, and `sendBeacon` are monkey-patched. A badge shows the network call count scoped to each query. Enable airplane mode after warm-up — the badge must stay green.

### Setup

```bash
cd moss-test
npm install
cp .env.example .env
# fill in MOSS_PROJECT_ID and MOSS_PROJECT_KEY from moss.dev dashboard
```

### Run

```bash
npm run dev
```

Open the local URL, wait for "Ready — safe to go offline ✈️", enable airplane mode, then click any query button.

---

## What's Not Here

- `moss-hacker-starter/` — vendored reference repo, excluded
- `*.pdf` — source protocol documents stay local
- `node_modules/`, `.env` — never committed
