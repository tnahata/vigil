# Vigil — Integration Plan: Data/Retrieval Layer ↔ LiveKit Voice Agent

> **Audience:** the teammate wiring the LiveKit + Minimax voice agent (currently on fake
> data) together with Ashish's data ingestion + Moss retrieval layer.
>
> **If you are Claude reading this in the agent teammate's session:** this is a handoff
> doc, not a finished spec. Before writing integration code, **work through the
> "Questions to resolve" section at the bottom and ask the user each open question.**
> Do not assume answers — the two codebases were built independently and the seams
> (env, schema, role-auth UX, fake-data shape) need confirmation. Treat every ❓ as a
> blocking question to put to the user.

---

## 1. The two codebases

| | **Data / retrieval layer** (Ashish — this repo) | **Voice agent** (you) |
|---|---|---|
| Where | `unsiloed-test/` + `moss-test/` | your agent (LiveKit). Draft reference: `moss-test/agent.py`, starter: `moss-hacker-starter/agent-py/` |
| Does | PDF → parsed JSON → `chunks.json` → **Moss index `vigil-protocol`**; drug aliasing, Tier-1/2 routing, population + role logic | wake word, STT, TTS, turn-taking, LLM (Tier-2), card to the app |
| State | **done & working** (CLI-verified via `query.py`) | working on **fake data**, needs to consume the real index |

**Goal of integration:** replace the agent's fake retrieval with real Moss queries against
`vigil-protocol`, and speak `value_spoken` verbatim on Tier-1 (the no-hallucination guarantee).

---

## 2. The data contract (what the index gives you)

- **Index name:** `vigil-protocol` (env `MOSS_INDEX_NAME`), embedding model `moss-minilm`
  (env `MOSS_MODEL_ID`). Built by `moss-test/create_index.py` from `unsiloed-test/chunks.json`.
- **88 chunks, 26 drugs.** Each chunk: `{ id, text, metadata }`.
- **`metadata` fields (all string-typed):**

  | field | values / meaning |
  |---|---|
  | `drug` | canonical name, e.g. `EPINEPHRINE (1:1,000)` — **exact string** the Tier-1 filter matches |
  | `indication` | e.g. `unstable bradycardia`, or `contraindication` |
  | `patient_type` | `adult` \| `pediatric` \| `all` (contraindications are `all`) |
  | `record_type` | `dose` \| `dose_weight_based` \| `contraindication` |
  | `value_spoken` | **➜ the string you send to TTS** (e.g. `"one milligram"`). May be empty for some chunks. |
  | `value_machine` | machine dose for the glance card (e.g. `atropine 1 mg IV/IO, MR q3-5 min`) |
  | `page`, `route`, `source` | citation + admin route for the card |

- **🔒 The safety contract:** on **Tier-1**, speak `metadata.value_spoken` **verbatim**. The LLM
  must never touch a dose number. Use `value_machine` + `page` only for the visual card.
  Peds weight-based doses come back as `value_spoken = "weight-based — see drug chart"` — speak that,
  don't invent a number.

---

## 3. Retrieval helpers to REUSE (don't re-implement — `agent.py` currently re-implements some, with bugs)

All in `moss-test/`:

- **`aliases.extract_drug_from_query(query) -> str | None`** — canonical drug or `None`.
  `None` ⇒ route Tier-2; a hit ⇒ route Tier-1. (Also `find_drug_span` returns the match offset.)
- **`query._classify_population(query, drug_pos) -> "adult" | "pediatric"`** — word-boundary +
  drug-proximity. **Use this.** `agent.py:75` has an older substring version that even treats
  `"weight"`/`"kg"` as pediatric, so "adult, weighs 90 **kg**" misroutes to peds.
- **`roles.extract_role_from_query / load_role_table / decide / spoken_answer`** — role gating
  (EMT/AEMT/PARAMEDIC → 🟢 dose / 🟡 dose+caveat / 🔴 withhold+redirect). Currently **only in
  `query.py`, not in the agent.** See `python3 moss-test/query.py --roles` for the full matrix.
- **Tier-1 query shape** (deterministic): `QueryOptions(top_k=1, alpha=0, filter={drug $eq, patient_type $eq})`,
  with a drug-only fallback. **Tier-2:** `QueryOptions(top_k=3-4, alpha=0.6)`.

`query.py` is the reference implementation of all routing — read it before changing the agent.

---

## 4. Integration steps

1. **Moss access.** Point the agent at the same Moss project so it loads the *same* index by name.
   `MossClient(MOSS_PROJECT_ID, MOSS_PROJECT_KEY)` → `await moss.load_index("vigil-protocol")` once on
   startup → `await moss.query(...)` thereafter (in-process, no network per query). ❓*same project or separate?*
2. **Swap fake retrieval → Moss.** Replace your stubbed lookup with the Tier-1/Tier-2 query shapes above.
   Map your fake-data fields onto the real `metadata` schema (§2). ❓*what shape is your fake data today?*
3. **Route** with `aliases.extract_drug_from_query` (drug present ⇒ Tier-1, else Tier-2).
4. **Tier-1 → speak `value_spoken`.** Adopt `query._classify_population` (drop the buggy `_is_peds`).
5. **Tier-2 → Minimax LLM** constrained to retrieved chunks, PII-redacted (pattern already in `agent.py:69`).
6. **Role gating?** Decide if/how voice gates by role (big UX question — see ❓ below).
7. **Card payload** to the app data channel — confirm the schema your frontend expects matches the
   Tier-1 `card` dict in `agent.py:209`.

---

## 5. Environment & run

```
# Moss (retrieval) — Ashish's layer
MOSS_PROJECT_ID=...        MOSS_PROJECT_KEY=...
MOSS_INDEX_NAME=vigil-protocol   MOSS_MODEL_ID=moss-minilm
# Minimax (Tier-2 LLM + TTS)
MINIMAX_API_KEY=...   MINIMAX_LLM_BASE_URL=https://api.minimaxi.chat/v1   MINIMAX_LLM_MODEL=MiniMax-Text-01
# LiveKit (transport + STT)
LIVEKIT_URL=...   LIVEKIT_API_KEY=...   LIVEKIT_API_SECRET=...
```

```bash
# 1. Build/refresh the index (Ashish's side, once; re-run if chunks.json changes)
cd unsiloed-test && python3 chunk.py
cd ../moss-test && python3 create_index.py --verify      # --dry-run validates offline, no creds

# 2. Run the agent (your side) — LiveKit standard commands
python agent.py console     # local mic test, no LiveKit room
python agent.py dev         # connect to a LiveKit room
# Say: "Vigil, what's the epi dose" → expect Tier-1 verbatim, no LLM in the log
```

(For LiveKit specifics — STT `inference.STT("deepgram/nova-3")`, Minimax `minimax.TTS(text_normalization=True)`,
turn detection, noise cancellation — use the **LiveKit docs MCP** in your session: `docs_search`, `get_python_agent_example`.)

---

## 6. Known vulnerabilities to respect (don't let the agent overclaim)

These exist in the retrieval layer today (full register + fixes: `~/.claude/plans/what-is-next-create-cozy-map.md`):

- **Indication-blind Tier-1:** `top_k=1` on (drug, population) only. 16 drug/population pairs have ≥2
  indications (e.g. ATROPINE adult: bradycardia **1 mg** vs organophosphate **2 mg**) — it returns one,
  context-blind. **Wrong-dose risk.**
- **Concentration collision:** `"epi"` → `EPINEPHRINE (1:1,000)` only; saying "epi" in a cardiac arrest
  returns the anaphylaxis IM dose, not the `1:10,000` IV dose.
- **KETAMINE unreachable** via Tier-1 (no alias yet).

The fix for these is being planned separately; until then, the agent should not claim "always the right dose."

---

## 7. ❓ Questions to resolve (ask the user before integrating)

**Moss / index**
1. Are we on **one shared Moss project** (so the agent loads the index Ashish already built), or separate projects (you must run `create_index.py` yourself)? Do you have the creds?
2. Confirm `MOSS_INDEX_NAME=vigil-protocol` and `MOSS_MODEL_ID=moss-minilm` on both sides.

**Your fake data → real schema**
3. What does your current fake retrieval return (shape/fields)? Can it map 1:1 onto the `metadata` schema in §2 (`value_spoken`, `value_machine`, `page`, `indication`, `patient_type`)?
4. Where in your code is the retrieval seam I should replace?

**TTS**
5. Are you already feeding `value_spoken` to Minimax TTS, with `text_normalization=True`? What voice/model?
6. What should TTS say when `value_spoken` is **empty** (6 chunks)? Fall back to `value_machine`, or a safe "see chart"?

**Routing / population**
7. Will you adopt `query._classify_population`, or keep your own peds detection? (Yours likely has the substring bug.)
8. Should "what's contraindicated with X" route to the `record_type=contraindication` chunk instead of returning the dose?

**Role authorization (voice UX)**
9. Do we gate doses by provider role in voice at all for the demo?
10. If yes — how does the medic declare their role hands-free? Per-utterance ("Vigil, I'm an EMT…"), once at session start (persist), or device/room config?
11. What exactly should a 🔴 not-authorized result *say* out loud (withhold + "seek a paramedic")? And 🟡 conditional (dose + caveat)?

**Tier-1 ambiguity (the §6 vulnerabilities)**
12. For multi-indication drugs (atropine) and multi-concentration drugs (epi) — should the agent **present both** options, ask a follow-up, or pick the most common? This is a clinical-safety decision.

**Tier-2 LLM**
13. Confirm Minimax model + key. Is the prompt-level "use ONLY these chunks / no invented numbers" constraint enough, or do we add a programmatic number-in-chunks check?

**Card / frontend**
14. What card payload schema does the app expect on the data channel? Does it match `agent.py`'s `card` dict?

**Shared code / drift**
15. Should `aliases.py`, `roles.py`, and `_classify_population` become a **shared module both repos import** (so the agent can't drift back to the old buggy logic)? Where should it live?

**Evals**
16. Do you want the Tier-1 gold-set correctness gate + adversarial "not in protocol" test wired into your LiveKit test suite?
