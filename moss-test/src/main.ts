/**
 * Vigil Phase-0 spike — fully offline Tier-1 EMT dosage lookup.
 *
 * Warm-up  (online):  download ONNX model → compute doc embeddings
 *                     → createIndex (Moss Cloud) → loadIndex (in-memory)
 * Query    (offline): embed query locally → query() in-memory → render card
 *
 * Network proof: fetch/XHR/beacon are monkey-patched. Counter must read 0
 * for queries fired after warm-up with airplane mode enabled.
 */

import { MossClient } from "@moss-dev/moss-web";
import type { MetadataFilter } from "@moss-dev/moss-web";
import { pipeline } from "@huggingface/transformers";

// ─── Config ──────────────────────────────────────────────────────────────────
// Injected at build time by vite.config.ts from MOSS_PROJECT_ID / MOSS_PROJECT_KEY
// (or VITE_MOSS_* variants). Declare so TypeScript knows these globals exist.
declare const __MOSS_PROJECT_ID__:  string;
declare const __MOSS_PROJECT_KEY__: string;

const PROJECT_ID  = __MOSS_PROJECT_ID__;
const PROJECT_KEY = __MOSS_PROJECT_KEY__;
const INDEX_NAME  = "emt-dosage-spike";
const ONNX_MODEL  = "Xenova/all-MiniLM-L6-v2";

if (!PROJECT_ID || !PROJECT_KEY) {
  fatal(
    "Moss credentials not found. Set MOSS_PROJECT_ID and MOSS_PROJECT_KEY " +
    "in your environment or in a .env file in moss-test/, then restart the dev server."
  );
}

// ─── Hardcoded EMT docs (5 representative drug entries) ──────────────────────
interface DocMeta { [key: string]: string; drug: string; indication: string; patient_type: string; route: string; value_spoken: string; }
interface SpikeDoc { id: string; text: string; metadata: DocMeta; }

const DOCS: SpikeDoc[] = [
  {
    id: "epi-1000-anaphylaxis-adult",
    text: "Epinephrine 1:1,000, anaphylaxis, adult: 0.5 mg IM, may repeat twice every 5 minutes.",
    metadata: { drug: "epinephrine", indication: "anaphylaxis", patient_type: "adult", route: "IM", value_spoken: "zero point five milligrams intramuscular" },
  },
  {
    id: "epi-10000-cardiac-arrest-adult",
    text: "Epinephrine 1:10,000, cardiac arrest, adult: 1 mg IV or IO every 3 to 5 minutes.",
    metadata: { drug: "epinephrine", indication: "cardiac arrest", patient_type: "adult", route: "IV", value_spoken: "one milligram intravenous or intraosseous" },
  },
  {
    id: "atropine-bradycardia-adult",
    text: "Atropine, unstable bradycardia, adult: 1 mg IV or IO, repeat every 3 to 5 minutes to maximum 3 mg.",
    metadata: { drug: "atropine", indication: "bradycardia", patient_type: "adult", route: "IV", value_spoken: "one milligram intravenous or intraosseous" },
  },
  {
    id: "naloxone-opioid-toxicity-adult",
    text: "Naloxone, opioid toxicity reversal, adult: 2 mg intranasal or intramuscular.",
    metadata: { drug: "naloxone", indication: "opioid toxicity", patient_type: "adult", route: "IN", value_spoken: "two milligrams intranasal or intramuscular" },
  },
  {
    id: "aspirin-acs-adult",
    text: "Aspirin, acute coronary syndrome, adult: 324 mg chewable by mouth.",
    metadata: { drug: "aspirin", indication: "acute coronary syndrome", patient_type: "adult", route: "PO", value_spoken: "three hundred twenty-four milligrams chewable" },
  },
];

// ─── Preset queries (text + metadata filter) ──────────────────────────────────
interface PresetQuery { label: string; text: string; filter: MetadataFilter; }

const QUERIES: PresetQuery[] = [
  {
    label: "Epi · anaphylaxis",
    text: "patient's throat is swelling shut, severe allergic reaction, how much epi do I give",
    filter: { $and: [
      { field: "drug",       condition: { $eq: "epinephrine" } },
      { field: "indication", condition: { $eq: "anaphylaxis"  } },
    ] },
  },
  {
    label: "Atropine · bradycardia",
    text: "heart rate is in the thirties, patient's bradycardic and symptomatic, what's the atropine dose",
    filter: { field: "drug", condition: { $eq: "atropine" } },
  },
  {
    label: "Naloxone · OD",
    text: "unresponsive, slow breathing, suspected heroin overdose, how much narcan",
    filter: { field: "drug", condition: { $eq: "naloxone" } },
  },
  {
    label: "Aspirin · ACS",
    text: "chest pain radiating to the arm, diaphoretic, looks like a heart attack, do I give aspirin and how much",
    filter: { field: "drug", condition: { $eq: "aspirin" } },
  },
];

// ─── Network interceptor ──────────────────────────────────────────────────────
// Monkey-patch before any imports fire network activity so nothing slips through.
let _queryActive  = false;
let _networkCount = 0;
const _netLog: string[] = [];

function _recordNet(label: string) {
  if (!_queryActive) return;
  _networkCount++;
  _netLog.push(label);
  renderNetworkBadge();
}

const _origFetch = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = input instanceof Request ? input.url : String(input);
  _recordNet(`fetch ${url.slice(0, 90)}`);
  return _origFetch(input, init);
};

const _origXhrOpen = XMLHttpRequest.prototype.open;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(XMLHttpRequest.prototype.open as any) = function (this: XMLHttpRequest, method: string, url: string) {
  _recordNet(`XHR ${method} ${String(url).slice(0, 90)}`);
  // eslint-disable-next-line prefer-rest-params
  return _origXhrOpen.apply(this, arguments as unknown as Parameters<typeof _origXhrOpen>);
};

if (navigator.sendBeacon) {
  const _origBeacon = navigator.sendBeacon.bind(navigator);
  navigator.sendBeacon = (url: string | URL, data?: BodyInit | null) => {
    _recordNet(`beacon ${String(url).slice(0, 90)}`);
    return _origBeacon(url, data);
  };
}

// ─── State ────────────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let embedder: any = null;
let mossClient: MossClient | null = null;
let ready = false;

// ─── Embed helper ─────────────────────────────────────────────────────────────
async function embed(text: string): Promise<number[]> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const out = await (embedder as any)(text, { pooling: "mean", normalize: true });
  return Array.from(out.data) as number[];
}

// ─── Warm-up ──────────────────────────────────────────────────────────────────
async function warmUp() {
  setStatus("warming", "Warming up…");

  // 1. Moss uses its own local WASM model for query embedding — ONNX not needed.
  //    (We keep the import for future BYOE work but skip the warm-up download.)

  // 2. Push docs to Moss Cloud — Moss embeds them server-side with its own model.
  //    After loadIndex(), query() uses Moss's local WASM model to embed the query
  //    and does cosine similarity entirely in-memory. No network during queries.
  mossClient = new MossClient(PROJECT_ID!, PROJECT_KEY!, { wasmUrl: "/moss_wasm_bg.wasm" });
  log("Creating Moss index (server-side embedding)…");
  try {
    await mossClient.createIndex(INDEX_NAME, DOCS);
    log("Index created");
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    // Treat "already exists" as a non-fatal condition
    if (/already exists|409/i.test(msg)) {
      log("Index already exists — reusing");
    } else {
      throw err;
    }
  }

  // 4. Download index into browser memory (after this, query() never hits the network)
  log("Loading index into browser memory…");
  await mossClient.loadIndex(INDEX_NAME);
  log("Index loaded — in-memory");

  // Mark ready
  ready = true;
  setStatus("ready", "Ready — safe to go offline ✈️");
  showOfflineNotice();
  enableQueryButtons();
  log("─────────────────────────────");
  log("Warm-up complete. Go offline, then click a query.");
}

// ─── Query ────────────────────────────────────────────────────────────────────
async function runQuery(preset: PresetQuery, btnEl: HTMLElement) {
  if (!ready || !mossClient) return;

  // Reset counter scoped to this query only
  _networkCount = 0;
  _netLog.length = 0;
  _queryActive = true;
  renderNetworkBadge();
  btnEl.classList.add("active");

  try {
    log(`Query: "${preset.text}"`);

    // query() embeds the text locally via Moss's WASM model and searches the
    // in-memory index — zero network calls after loadIndex().
    // Filtered query — drives the result card
    const { docs } = await mossClient.query(INDEX_NAME, preset.text, {
      topK: 1,
      filter: preset.filter,
    });

    // Unfiltered top-3 — sanity-check: shows how all docs rank semantically
    const { docs: allDocs } = await mossClient.query(INDEX_NAME, preset.text, { topK: 3 });
    log(`Semantic ranking (no filter):`);
    allDocs.forEach((d, i) => log(`  ${i + 1}. ${d.id} (score=${d.score?.toFixed(3) ?? "?"})`));
    log(`Filtered result: ${docs[0]?.id ?? "none"} (score=${docs[0]?.score?.toFixed(3) ?? "?"})`);

    renderCard(docs[0]);
  } catch (err: unknown) {
    log(`ERROR: ${err instanceof Error ? err.message : String(err)}`);
  } finally {
    _queryActive = false;
    btnEl.classList.remove("active");
    renderNetworkBadge(); // final state
  }
}

// ─── UI helpers ───────────────────────────────────────────────────────────────
const $log      = document.getElementById("log-panel")!;
const $statusDot  = document.getElementById("status-dot")!;
const $statusText = document.getElementById("status-text")!;
const $netBadge   = document.getElementById("network-badge")!;
const $netCount   = document.getElementById("network-count")!;
const $netLog     = document.getElementById("net-log")!;
const $card       = document.getElementById("result-card")!;
const $buttons    = Array.from(document.querySelectorAll<HTMLButtonElement>(".query-btn"));

function log(msg: string) {
  $log.textContent += msg + "\n";
  $log.scrollTop = $log.scrollHeight;
}

function setStatus(state: "warming" | "ready" | "error", text: string) {
  $statusDot.className = state;
  $statusText.textContent = text;
}

function showOfflineNotice() {
  document.getElementById("offline-notice")!.classList.add("visible");
}

function enableQueryButtons() {
  $buttons.forEach((btn, i) => {
    btn.disabled = false;
    btn.addEventListener("click", () => runQuery(QUERIES[i]!, btn));
  });
}

function renderNetworkBadge() {
  $netCount.textContent = String(_networkCount);
  $netBadge.className = _networkCount === 0 ? "clean" : "dirty";
  $netLog.textContent = _netLog.length
    ? _netLog.map((l) => "  " + l).join("\n")
    : _networkCount === 0 && !_queryActive ? "" : "";
}

function renderCard(result: unknown) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const r = result as any;
  const id: string = r?.id ?? "";
  const score: number | undefined = r?.score;

  // Look up metadata from our local DOCS array by id — Moss may return an
  // empty metadata object from the loaded index, so we don't rely on it.
  const doc = DOCS.find((d) => d.id === id);
  if (!doc) { log("No result returned"); return; }

  (document.getElementById("card-spoken")!     as HTMLElement).textContent = doc.metadata.value_spoken;
  (document.getElementById("card-drug")!       as HTMLElement).textContent = doc.metadata.drug;
  (document.getElementById("card-indication")! as HTMLElement).textContent = doc.metadata.indication;
  (document.getElementById("card-patient")!    as HTMLElement).textContent = doc.metadata.patient_type;
  (document.getElementById("card-route")!      as HTMLElement).textContent = doc.metadata.route;
  (document.getElementById("card-text")!       as HTMLElement).textContent = r?.text ?? doc.text;
  (document.getElementById("result-score")!    as HTMLElement).textContent =
    score !== undefined ? `relevance score: ${score.toFixed(4)}` : "";

  $card.classList.add("visible");
}

function fatal(msg: string) {
  document.body.innerHTML = `<div style="color:#ef4444;font-family:monospace;padding:2rem">${msg}</div>`;
  throw new Error(msg);
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
warmUp().catch((err: unknown) => {
  const msg = err instanceof Error ? err.message : String(err);
  setStatus("error", `Error: ${msg}`);
  log(`FATAL: ${msg}`);
});
