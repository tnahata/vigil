# CLAUDE.md — Vigil

> **Vigil** — a hands-free voice copilot for EMTs: ask for a drug dose or contraindication out loud, hear the exact protocol answer back, hands and eyes stay on the patient.
> Team repo: github.com/tnahata/vigil ("EMT Voice Copilot"). 

---

## 0. What Vigil is, and the one claim we defend

A medic on a cardiac-arrest or pediatric-anaphylaxis call needs a weight-based dose where a decimal-point error is fatal, and they can't look at a screen. Vigil lets them **ask out loud and get the exact dose spoken back**, with the dangerous part — the number — coming straight from the source protocol, never from a language model.

**The claim we defend in front of judges:** *"It is structurally impossible for Vigil to hallucinate a dose, because the LLM is architecturally removed from the dose path."* That is our differentiator. Correctness and safety are the hero of the demo, not latency.

**What we are NOT claiming (don't overclaim — a sharp judge will catch it):** Moss runs **server-side in the agent**, so this is not an offline/on-device product. There is no "works in airplane mode on the phone" story. The win is the deterministic, no-hallucination dose path plus fast in-process retrieval — not edge/offline.

---

## 1. Interaction model

- **Wake word "Vigil" is the trigger.** STT runs always-on; the agent watches the transcript for the literal token "vigil" and treats what follows as the query. No touch-to-speak, no Porcupine — transcript keyword detection is enough for the demo.
- **Reactive only, never speaks unprompted.** Always-on STT exists only to catch the wake word; there is **no passive monitoring** — nothing is analyzed, retrieved, or staged until "Vigil" is heard.
- **Speculative retrieval is allowed, but gated.** Only AFTER the first "Vigil" interaction in a session, and only WITHIN a triggered utterance: as interim STT partials stream in, the agent fires in-process Moss queries to pre-warm the answer. Cheap because Moss is in-process (<10 ms). Do not enable it before the first interaction, and do not retrieve on untriggered background speech.

---

## 2. Architecture & data flow

```
React Native app (Expo dev build)            <- thin client: mic + speaker + glance card
  --mic audio (always-on)-->
LiveKit Cloud  (real-time transport + Inference STT)
  --transcript-->
Python LiveKit agent  (your server)          <- the brain
   - detect wake word "Vigil", endpoint the turn
   - route: Tier 1 (dose/contraindication) vs Tier 2 (soft synthesis)
   - Moss IN-PROCESS retrieval  (0 network, <10 ms)
   - Tier 2 only: Minimax LLM (constrained to retrieved chunks)
   - Minimax TTS  -> session.say(spoken_form)
  --answer audio + card payload (data channel)-->
React Native app  (plays audio, flashes card)
```

**Call count per Tier-1 query (this is what "how many calls" resolves to):**
- LiveKit transport: audio up, audio + card down.
- LiveKit Inference STT: 1 (no separate Deepgram account — runs on your LiveKit key).
- Moss query: in-process, **0 network**.
- LLM: **none** on the dose path.
- Minimax TTS: 1.

**Tier-2 adds exactly one thing:** a Minimax LLM call after hybrid retrieval. Everything else is identical.

---

## 3. Verified tech stack (grounded against live docs, June 2026)

### Client — React Native (Expo dev build), thin
- Install: `@livekit/react-native @livekit/react-native-webrtc livekit-client`; for Expo add `@livekit/react-native-expo-plugin @config-plugins/react-native-webrtc` to `app.json` plugins. Call `registerGlobals()` in `index.js` (sets up WebRTC for JS — required).
- Responsibilities: join the room, publish mic audio (always-on), play the agent's audio, render one big high-contrast glance card (sunlight + gloves = huge text, contraindications in red) from the data channel. That's it — no retrieval, no model calls client-side.
- **AEC** (echo cancellation, so the mic doesn't hear the agent's own voice during always-on STT) is handled by the native WebRTC layer client-side. Don't disable it.
- **Phase-0 spike (do early):** get a hello-world dev build on a REAL device (mic permission, join room, receive a data message). **Fallback if signing/provisioning drags:** mobile-web client (LiveKit JS in Safari). Because retrieval is server-side, the web fallback is functionally identical — no re-architecting.

### Audio in — LiveKit Inference STT
- Use `inference.STT("deepgram/nova-3", language="multi")` via the LiveKit `inference` module — one LiveKit key, no separate provider account, runs on LiveKit infra. Switch to the standalone Deepgram plugin only if you later need provider-specific features.
- LiveKit is the framework/transport; it does not transcribe by itself — STT is one of three pipeline models (STT -> LLM -> TTS).

### Turn-taking, interruptions, noise — LiveKit (server-side, in the agent)
- Turn-detector model waits through natural mid-sentence pauses (so "Vigil, what's the... uh... peds epi dose" isn't cut off early).
- Adaptive interruption handling (default on LiveKit Cloud, Python Agents v1.5.0+) separates real interrupts from backchannels/noise.
- Noise cancellation via `livekit-plugins-noise-cancellation` added to `room_input_options`.
- **Silero VAD is deferred.** Noise cancellation cleans the signal; VAD decides when speech is present — different jobs, not redundant. For the demo, rely on the turn-detector model + STT endpointing + noise cancellation; add/tune `silero` later only if segmentation in the noisy environment is poor.

### Retrieval — Moss, SERVER-SIDE, in-process in the Python agent
- **Use the Moss CLI** during the ingestion/verification phase to create, load, inspect, and query the index — sanity-check the alias matching and `alpha` direction before any agent code.

- Metadata operators: `$eq`, `$and`, `$in`, `$near`. Namespace peds vs adult so a query can never cross populations.
- **VERIFY alpha direction in the CLI/REPL** before trusting it (expected: 0 ≈ keyword, 1 ≈ semantic).

### Reasoning — Minimax LLM (Tier 2 only)
- TrueFoundry is REMOVED. Tier-2 calls Minimax directly (we have credits). Keep the model/provider a **config/env value** so it stays swappable.
- Constrained: must cite retrieved chunks and must NOT emit any number not present in retrieval.
- **PII:** Use a lightweight regex/NER redaction step in the Python server that strips patient identifiers BEFORE the Minimax LLM call. Minimax key lives only on the server.

### Voice out — Minimax TTS via LiveKit
- `livekit-plugins-minimax-ai` (Python), `MINIMAX_API_KEY`. Speak with `session.say(spoken_form)`. Reactive, short (~10–30 tokens).
- **Dose-pronunciation safety (two belts):** (1) store a `spoken_form` field next to the machine value in every index doc and send exactly that to TTS; (2) use Minimax's `pronunciation_dict` / `text_normalization` so "0.01 mg" is read correctly. The `spoken_form` string is the real guarantee.

### Observability
- Self-instrument: timestamp each stage in the agent (STT done, retrieval done, TTS first byte) and log/emit them. Latency is a supporting beat now, not the headline.

---

## 4. Two-tier retrieval (the safety core)

- **Tier 1 — dose / contraindication (deterministic, life-critical).** Pure **exact keyword** match (`alpha = 0`, no semantic component) + metadata `$eq` filter on canonical `drug` and `population`. At that point it's a filtered exact lookup, not fuzzy search — and it needs no embedding, so it's fastest and fully deterministic. Returns the **verbatim** protocol chunk (dose + citation); the agent speaks `spoken_form` and renders the card. **No LLM, ever.**
  - **Mandatory alias normalization:** exact keyword whiffs on synonyms ("adrenaline" vs "epinephrine", "epi", brand names). Before the keyword match, extract the drug and map it to the canonical name via a small alias dictionary. Without this, real queries miss and the 100% gate fails on phrasing, not retrieval. This is the make-or-break detail for Tier 1.
- **Tier 2 — soft synthesis (sequencing, "what should I consider", "contraindicated given X").** Hybrid retrieval with a **tunable alpha (~0.5–0.7, semantic-leaning)** — keyword anchors keep exact protocol terms while semantics add recall. Retrieved chunks feed the Minimax LLM (constrained as above), then TTS.

---

## 5. Evals (correctness first) & demo

**Evals — end-to-end correctness is primary** (run the whole pipeline, check the answer the medic actually gets, not just whether Moss returned a row):
- **Tier 1 = a hard 100% gate.** Exact-match on dose + protocol ID across the gold set (hand-derived from the source PDF). Because Tier 1 is verbatim-from-retrieval, anything below 100% is a routing/alias/retrieval bug to fix before demo, not acceptable variance.
- **Tier 2 = LLM-as-judge groundedness** (different model: "any clinical claim or number unsupported by these chunks? yes/no"). Score = % with zero unsupported claims.
- **Adversarial subset (the safety money-shot):** a drug not in protocol, an out-of-range weight, a contraindicated combo → assert it says *"not in protocol — contact medical control"* rather than inventing.
- Latency self-instrumented, reported as secondary.

---

## 6. Ingestion
being worked on by another teammate at the moment on a diff repo branch.

---

## 7. Repo & git hygiene (DISQUALIFICATION RISK)
- Doc/planning iteration stays in a separate repo, never pushed to the code repo.
- Auto-commit after every completed mission.
- Layout: align with the existing repo; suggested `/agent` (Python) + `/app` (React Native).

---
