# Vigil — Data/Retrieval Layer Summary (handoff)

**Branch:** `unsiloed-test-ashish` | **Owner:** Ashish (ingestion + retrieval) | **Updated:** 2026-06-06

> This summarizes the **data ingestion + Moss retrieval layer** that's done and working, for
> handoff to the LiveKit voice-agent integration. **Integration steps + open questions live in
> [`plan.md`](plan.md)** — start there if you're wiring the agent to this data.

---

## Repo layout for the Unsiloed aspect

```
vigil/
├── unsiloed-test/              ← ingestion pipeline
│   ├── parse_pdf.py            Stage 1: PDF → Unsiloed API → parsed_output.json (cached)
│   ├── chunk.py                Stage 2: parsed_output.json → chunks.json
│   ├── chunks.json             Moss-ready docs (88 chunks) — gitignored, regenerate locally
│   ├── parsed_output.json      cached Unsiloed output (27 pages) — gitignored
│   ├── reparse_compare.py      re-parse to a new file + diff vs cached (vendor drift check)
│   └── sd_ems_p115.pdf         source protocol PDF — gitignored
├── moss-test/                  ← retrieval + helpers (and the draft agent)
│   ├── create_index.py         builds the Moss index `vigil-protocol` from chunks.json
│   ├── aliases.py              drug synonym → canonical name (Tier-1 trigger)
│   ├── query.py                REFERENCE routing: Tier-1/2, population, role gating, --roles, --bench
│   ├── roles.py                role authorization (EMT/AEMT/PARAMEDIC), PDF-sourced
│   ├── extract_role_auth.py    regenerates roles._VERIFIED_PAGE_AUTH from the PDF (offline)
│   └── agent.py                DRAFT LiveKit agent (team owns final integration)
├── app/                        ← React Native Expo thin client (mic + speaker + glance card)
├── moss-hacker-starter/        ← vendored LiveKit reference (agent-py/, frontend/)
├── plan.md                     ← INTEGRATION PLAN + question bank  ← read this to integrate
├── summary.md                  ← this file
└── CLAUDE.md                   ← project spec + architecture constraints
```

There is **no `agent/` directory** — the agent code is `moss-test/agent.py`.

---

## Architecture & call count

```
React Native app  ──mic──▶  LiveKit (transport + Inference STT: deepgram/nova-3)  ──transcript──▶
Python LiveKit agent:
   wake word "vigil" ─┬─ Tier 1 (drug detected via aliases.py)
                      │     → Moss keyword query (alpha=0, drug + patient_type filter, top_k=1)
                      │     → session.say(value_spoken)        ← NO LLM, ever
                      │     → publish glance card (data channel)
                      └─ Tier 2 (no drug)
                            → Moss hybrid query (alpha=0.6, top_k=3-4)
                            → Minimax LLM (constrained to chunks, PII-redacted) → session.say(answer)
   Minimax TTS (text_normalization=True for dose numbers)  ──audio + card──▶  app
```

**Per Tier-1 query:** LiveKit STT (1) + Moss in-process (**0 network**) + Minimax TTS (1) + LLM (**0**).
Tier-2 adds exactly one Minimax LLM call.

---

## The data contract (what the agent consumes)

- **Index:** `vigil-protocol`, model `moss-minilm`. **88 chunks, 26 drugs.**
- **Chunk:** `{ id, text, metadata }`. Metadata (all string-typed):
  `drug`, `indication`, `patient_type` (`adult`|`pediatric`|`all`), `record_type`
  (`dose`|`dose_weight_based`|`contraindication`), `value_spoken` *(→ TTS)*, `value_machine` *(→ card)*,
  `page`, `route`, `source`.
- **Record types:** `dose` (44), `dose_weight_based` (32, peds → "weight-based — see drug chart"),
  `contraindication` (12, `patient_type=all`).
- **🔒 Speak `value_spoken` verbatim on Tier-1.** `value_machine`/`page` are for the card only.

Full field table + Tier-1/Tier-2 query shapes are in [`plan.md` §2–3](plan.md).

---

## Role-based authorization (this session)

Every drug page colors EMT / AEMT / PARAMEDIC by who may administer it (🟢 authorized /
🟡 LEMSA-conditional / 🔴 not authorized). Sourced **deterministically from the PDF's header fills**
(`extract_role_auth.py`, validated 13/13 against the colors Unsiloed emitted) because Unsiloed drops
those colors non-deterministically — see [[unsiloed-header-color-nondeterminism]]. Baked into
`roles._VERIFIED_PAGE_AUTH` (26 drugs). `query.py` gates Tier-1: 🟢 speak dose, 🟡 dose + the limitation
caveat from the Notes, 🔴 withhold + "seek a paramedic". Run `python3 moss-test/query.py --roles` for the matrix.

**Status:** implemented in the **CLI harness (`query.py`) only — not yet in the voice agent.** Porting it
(and the UX of declaring a role hands-free) is an open integration question in [`plan.md` §7](plan.md).

---

## Pipeline mechanics & key fixes (already done)

- **Ingestion:** `sd_ems_p115.pdf` (27 pp) → `parse_pdf.py` (Unsiloed API, cached) → `chunk.py` → `chunks.json`.
  `create_index.py` prints a build plan, runs a **quality gate** (fails on markdown leakage/dup ids) before push,
  and supports `--dry-run` / `--verify`.
- **value_spoken safety:** weight-normalized doses speak "…per kilogram"; mass-over-volume totals speak the mass
  ("one gram" for `1 gm/10 mL`), diluent volumes stripped first (avoids speaking "100 mL" as the dose); peds
  weight-based defer to the chart.
- **Population routing fix (in `query.py`):** word-boundary + drug-proximity classification replaced a substring
  check that mis-fired on concatenated/ambiguous phrasing. **Note:** `agent.py` still has the older buggy version.
- **Retrieval latency:** in-process Moss queries land ~3–7 ms (sub-10 ms) once warm; no result cache — the warm-up
  is the embedding model + thread pool.

---

## Known gaps / risks (full register in `~/.claude/plans/what-is-next-create-cozy-map.md`)

- **Indication-blind Tier-1** (16 drug/pop pairs, e.g. atropine 1 mg vs 2 mg) — `top_k=1` returns one, context-blind.
- **Concentration collision** — `"epi"` → `1:1,000` only (cardiac-arrest `1:10,000` not reached by the generic alias).
- **KETAMINE has no alias** → unreachable via Tier-1 (the *chunk* exists; the *alias* is missing).
- **Contraindication intent** — "what's contraindicated with X" returns the dose, not the contraindication chunk.
- **No Tier-1 100% gold-set eval / adversarial subset** yet.

---

## Next steps

1. **Integrate the agent** → follow [`plan.md`](plan.md) and answer its question bank.
2. **Tier-1 gold-set eval** (all drugs × phrasings, 100% exact) + adversarial "not in protocol" — highest leverage; catches the gaps above.
3. **Close P0/P1** (indication/concentration disambiguation, ketamine alias, contraindication routing).
4. **Re-index** after any `chunk.py` change: `python3 unsiloed-test/chunk.py && python3 moss-test/create_index.py`.
