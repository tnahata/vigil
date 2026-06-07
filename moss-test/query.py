"""Interactive query harness for the Vigil Moss index — with PDF verification.

For each query it:
  1. Routes the way the agent does:
       - Tier 1 if a drug alias is detected -> keyword query (alpha=0) with a
         drug (+ population) metadata filter. Deterministic, no LLM.
       - Tier 2 otherwise -> hybrid query (alpha=0.6), semantic-leaning.
  2. Prints the matched chunk (spoken dose, machine value, page, score).
  3. Prints the ORIGINAL protocol source for that page (from parsed_output.json)
     so you can cross-check the answer against the same page of the PDF
     (unsiloed-test/sd_ems_p115.pdf).

Add a provider role to any query to gate the answer by who may administer the
drug ("I'm an EMT, how much atropine" -> withheld + redirect; see roles.py).

Usage:
    python3 query.py                       # interactive REPL
    python3 query.py "how much epi for a kid with anaphylaxis"
    python3 query.py "I'm an EMT, what's the atropine dose"   # role-gated
    python3 query.py --roles               # print the role authorization matrix (offline)
    python3 query.py --demo                # run a preset colloquial set
    python3 query.py --bench               # 100x per demo query: min/med/p95/mean
    python3 query.py --bench --iters=500   # custom iteration count
    python3 query.py --pause               # pause after load so you can kill wifi
    python3 query.py --pause --bench       # load online, go offline, then bench

Add --pause to ANY mode: it loads the index (the only networked step), then
waits for Enter so you can disable wifi and prove queries are fully in-process.

Needs MOSS_PROJECT_ID / MOSS_PROJECT_KEY in moss-test/.env and a built index
(run: python3 create_index.py   first).
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from moss import MossClient, QueryOptions

import re

from aliases import extract_drug_from_query, find_drug_span
import roles as roles_mod

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
PARSED_PATH = BASE_DIR.parent / "unsiloed-test" / "parsed_output.json"
PDF_PATH = BASE_DIR.parent / "unsiloed-test" / "sd_ems_p115.pdf"

load_dotenv(ENV_PATH)
INDEX = os.getenv("MOSS_INDEX_NAME", "vigil-protocol")

# Word-boundary matched so "pediatric" can't match inside "pediatricshow" and
# so an explicit "adult" is detected positively rather than assumed by default.
_PEDS_RE = re.compile(
    r"\b(?:peds|pediatric|pediatrics|paediatric|paediatrics|child|children|"
    r"kid|kids|infant|infants|baby|babies|newborn|neonate|neonatal|toddler)\b"
)
_ADULT_RE = re.compile(r"\b(?:adult|adults|grown[ -]?(?:up|man|woman)?|elderly|geriatric)\b")

DEMO_QUERIES = [
    "my kid is having an allergic reaction his throat is closing how much epi",
    "guy od'd on heroin not breathing how much narcan",
    "chest pain looks like a heart attack how much aspirin do I give",
    "heart rate is in the 30s and he's out of it whats the atropine dose",
    "she's seizing and won't stop what do I push",
    "bad bleeding from trauma can I give txa and how much",
    "what's contraindicated with nitro",
    "how much tylenol for pain",
]


def _classify_population(query: str, drug_pos: int | None = None) -> str:
    """Resolve 'pediatric' vs 'adult' from a colloquial query.

    A wrong population can surface a confidently-wrong dose, so this is more
    careful than "any peds word -> peds":
      - only peds terms present     -> pediatric
      - only adult terms present    -> adult
      - BOTH present (e.g. "stridor in peds ... epi for an adult") -> the term
        nearest the drug mention wins, since that's the one qualifying the dose
        being asked for; with no drug anchor, the last-mentioned term wins.
      - neither present             -> adult (protocol default)
    """
    ql = query.lower()
    peds = [m.start() for m in _PEDS_RE.finditer(ql)]
    adult = [m.start() for m in _ADULT_RE.finditer(ql)]
    if peds and not adult:
        return "pediatric"
    if adult and not peds:
        return "adult"
    if peds and adult:
        if drug_pos is not None:
            return "pediatric" if min(abs(p - drug_pos) for p in peds) < \
                min(abs(a - drug_pos) for a in adult) else "adult"
        return "pediatric" if max(peds) > max(adult) else "adult"
    return "adult"


def _load_source_by_page() -> dict[int, dict]:
    """page_number -> {'drug': header text, 'tables': [markdown, ...]}."""
    if not PARSED_PATH.exists():
        return {}
    with PARSED_PATH.open() as f:
        data = json.load(f)
    segs = [s for c in data.get("chunks", []) for s in c.get("segments", [])]
    pages: dict[int, dict] = {}
    for s in segs:
        p = s.get("page_number")
        if p is None:
            continue
        entry = pages.setdefault(p, {"drug": None, "tables": []})
        st = s.get("segment_type")
        md = (s.get("markdown") or "").strip()
        if st == "SectionHeader" and md:
            entry["drug"] = md.lstrip("#").strip()
        elif st == "Text" and md.isupper() and len(md) < 80 and not entry["drug"]:
            entry["drug"] = md
        elif st == "Table" and md:
            entry["tables"].append(md)
    return pages


def _fmt_doc(doc) -> str:
    m = getattr(doc, "metadata", {}) or {}
    score = getattr(doc, "score", None)
    score_s = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
    return (
        f"    id        : {doc.id}\n"
        f"    drug      : {m.get('drug', '')}\n"
        f"    indication: {m.get('indication', '')}\n"
        f"    population : {m.get('patient_type', '')}   record_type: {m.get('record_type', '')}\n"
        f"    SPOKEN    : {m.get('value_spoken', '') or '(none)'}\n"
        f"    machine   : {m.get('value_machine', '')}\n"
        f"    page      : {m.get('page', '')}   route: {m.get('route', '') or '-'}   score: {score_s}"
    )


async def _timed_query(client: MossClient, text: str, opts: QueryOptions) -> tuple[list, float]:
    """Run one Moss query, returning (docs, elapsed_ms). Times ONLY the call."""
    t0 = time.perf_counter()
    res = await client.query(INDEX, text, opts)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return (getattr(res, "docs", None) or []), elapsed_ms


_STATE_BADGE = {
    roles_mod.AUTHORIZED: "🟢 AUTHORIZED",
    roles_mod.CONDITIONAL: "🟡 CONDITIONAL (LEMSA-limited)",
    roles_mod.NOT_AUTHORIZED: "🔴 NOT AUTHORIZED",
    roles_mod.UNKNOWN: "⬜ UNKNOWN",
}


def _print_authorization(
    role: str | None, drug: str, meta: dict, role_table: dict[int, dict]
) -> None:
    """Role-gate the dose: speak it, caveat it, or refuse + redirect."""
    dose_spoken = meta.get("value_spoken") or meta.get("value_machine") or "(see chart)"
    if role is None:
        print("\n  🔐 AUTHORIZATION: no provider role stated — dose shown ungated.")
        print("     (say e.g. \"I'm an EMT\" to role-gate the answer)")
        return

    try:
        page = int(str(meta.get("page", "")))
    except (TypeError, ValueError):
        page = None
    page_auth = role_table.get(page) if page is not None else None
    if not page_auth:
        print(f"\n  🔐 AUTHORIZATION ({role}): no role-color data for this drug in the "
              "parse — dose shown ungated.")
        return

    state, caveat, allowed = roles_mod.decide(page_auth, role)
    spoken = roles_mod.spoken_answer(drug, dose_spoken, role, state, caveat, allowed)
    print(f"\n  🔐 AUTHORIZATION ({role}): {_STATE_BADGE.get(state, state)}")
    cols = "  ".join(f"{r}={page_auth['roles'].get(r, '?')}" for r in roles_mod.ROLES)
    print(f"     header: {cols}")
    if state == roles_mod.NOT_AUTHORIZED:
        print(f"     ⛔ dose withheld — seek {roles_mod._join_roles(allowed)}")
    print(f"  🔊 SPOKEN ANSWER: {spoken}")


async def run_query(
    client: MossClient,
    source: dict[int, dict],
    query: str,
    role_table: dict[int, dict] | None = None,
) -> None:
    print("\n" + "=" * 72)
    print(f"QUERY: {query!r}")
    print("=" * 72)

    # Routing (alias extraction + population + role) is pure local regex and is
    # NOT retrieval — time it separately so the retrieval metric below is strictly
    # the Moss query call, never routing/formatting overhead.
    t0 = time.perf_counter()
    span = find_drug_span(query)
    drug = span[0] if span else None
    population = _classify_population(query, span[1] if span else None)
    role = roles_mod.extract_role_from_query(query)
    route_ms = (time.perf_counter() - t0) * 1000.0

    if drug:
        role_note = f" | role: {role}" if role else ""
        print(f"routing -> TIER 1 (drug detected: {drug} | population guess: {population}{role_note})")
        filters = [
            {"$and": [
                {"field": "drug", "condition": {"$eq": drug}},
                {"field": "patient_type", "condition": {"$eq": population}},
            ]},
            {"field": "drug", "condition": {"$eq": drug}},  # fallback: drug only
        ]
        chosen = None
        retrieval_ms = 0.0   # the call that actually returned the spoken dose
        miss_ms = 0.0        # time spent on a population filter that missed (not the answer)
        for i, filt in enumerate(filters):
            docs, ms = await _timed_query(client, drug, QueryOptions(top_k=1, alpha=0, filter=filt))
            if docs:
                chosen = docs[0]
                retrieval_ms = ms
                if i == 1:
                    print("    (no exact population match — fell back to drug-only filter)")
                break
            miss_ms += ms
        print(f"\n  ⏱  routing (local regex, not retrieval): {route_ms:.3f} ms")
        if chosen is None:
            print(f"  ⏱  retrieval: {miss_ms:.3f} ms (no hit)")
            print("    NO Tier-1 hit. (Drug recognized but no matching chunk — check the index.)")
            return
        print(f"  ⏱  retrieval (Moss query that returned the dose): {retrieval_ms:.3f} ms")
        if miss_ms:
            print(f"      (+ {miss_ms:.3f} ms on the population-filter attempt that missed, then fell back)")
        print("  MOSS RESULT (top-1, alpha=0, keyword + metadata filter):")
        print(_fmt_doc(chosen))
        meta = getattr(chosen, "metadata", {}) or {}
        page = meta.get("page", "")
        _print_authorization(role, drug, meta, role_table or {})
    else:
        print("routing -> TIER 2 (no drug alias detected -> hybrid semantic, alpha=0.6)")
        docs, retrieval_ms = await _timed_query(client, query, QueryOptions(top_k=3, alpha=0.6))
        print(f"\n  ⏱  routing (local regex, not retrieval): {route_ms:.3f} ms")
        if not docs:
            print(f"  ⏱  retrieval: {retrieval_ms:.3f} ms (1 in-process call)")
            print("    NO Tier-2 hits.")
            return
        print(f"  ⏱  retrieval (Moss hybrid query): {retrieval_ms:.3f} ms (1 in-process call)")
        print("  MOSS RESULTS (alpha=0.6, hybrid — top 3):")
        for d in docs:
            print(_fmt_doc(d))
            print("    " + "-" * 60)
        page = getattr(docs[0], "metadata", {}).get("page", "")

    # ---- show the original source for verification against the PDF ----
    try:
        pnum = int(str(page))
    except (TypeError, ValueError):
        pnum = None
    if pnum is not None and pnum in source:
        src = source[pnum]
        print(f"\n  --- SOURCE: parsed page {pnum} (open {PDF_PATH.name} p.{pnum} to confirm) ---")
        if src["drug"]:
            print(f"  header: {src['drug']}")
        for md in src["tables"]:
            print("  " + md.replace("\n", "\n  "))
    else:
        print(f"\n  (no cached source for page {page!r} — open the PDF to verify)")


def _route(query: str) -> tuple[str, str, QueryOptions]:
    """Return (tier, query_text, options) for the PRIMARY retrieval call.

    Mirrors run_query's routing but without the Tier-1 fallback — bench measures
    the single representative call so the latency numbers are comparable.
    """
    span = find_drug_span(query)
    if span:
        drug, drug_pos = span
        population = _classify_population(query, drug_pos)
        filt = {"$and": [
            {"field": "drug", "condition": {"$eq": drug}},
            {"field": "patient_type", "condition": {"$eq": population}},
        ]}
        return "tier1", drug, QueryOptions(top_k=1, alpha=0, filter=filt)
    return "tier2", query, QueryOptions(top_k=3, alpha=0.6)


def _stats(samples: list[float]) -> tuple[float, float, float, float]:
    s = sorted(samples)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return s[0], statistics.median(s), p95, statistics.fmean(s)


async def bench(client: MossClient, queries: list[str], iters: int) -> None:
    print(f"\n{'=' * 78}")
    print(f"BENCH — {iters} iterations per query (timing the in-process query call only)")
    print(f"{'=' * 78}")
    print(f"  {'tier':5} {'min':>8} {'med':>8} {'p95':>8} {'mean':>8}   query")
    print(f"  {'-' * 74}")
    all_samples: list[float] = []
    for q in queries:
        tier, text, opts = _route(q)
        samples = []
        for _ in range(iters):
            _, ms = await _timed_query(client, text, opts)
            samples.append(ms)
        all_samples += samples
        mn, md, p95, mean = _stats(samples)
        label = q if len(q) <= 40 else q[:37] + "..."
        print(f"  {tier:5} {mn:8.3f} {md:8.3f} {p95:8.3f} {mean:8.3f}   {label!r}")
    print(f"  {'-' * 74}")
    mn, md, p95, mean = _stats(all_samples)
    print(f"  {'ALL':5} {mn:8.3f} {md:8.3f} {p95:8.3f} {mean:8.3f}   ({len(all_samples)} samples)")
    print("\n  All times in milliseconds. Moss advertises <10 ms in-process retrieval.")


_ROLE_CELL = {
    roles_mod.AUTHORIZED: "🟢 GREEN ",
    roles_mod.CONDITIONAL: "🟡 YELLOW",
    roles_mod.NOT_AUTHORIZED: "🔴 RED   ",
    roles_mod.UNKNOWN: "⬜ ?     ",
}


def print_role_matrix() -> None:
    """Offline: print who may administer each drug (no Moss/credentials needed)."""
    source = _load_source_by_page()
    role_table = roles_mod.load_role_table(PARSED_PATH)
    print("\n" + "=" * 72)
    print("ROLE AUTHORIZATION MATRIX — who may administer each drug")
    print("  source: header fills in sd_ems_p115.pdf (roles._VERIFIED_PAGE_AUTH)")
    print("=" * 72)
    print(f"  {'pg':>3}  {'drug':30} {'EMT':9} {'AEMT':9} {'PARAMEDIC':9}")
    print(f"  {'-' * 68}")
    for page in sorted(role_table):
        drug = (source.get(page, {}).get("drug") or "").replace("\n", " ")[:30]
        r = role_table[page]["roles"]
        cells = "  ".join(_ROLE_CELL[r[role]] for role in roles_mod.ROLES)
        print(f"  {page:>3}  {drug:30} {cells}")
    print(f"  {'-' * 68}")
    print(f"  {len(role_table)} drugs covered. 🟡 = LEMSA-conditional (limited scope; "
          "see Notes caveat).")


async def main() -> None:
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    demo = "--demo" in flags
    do_bench = "--bench" in flags
    pause = "--pause" in flags
    iters = next((int(f.split("=", 1)[1]) for f in flags if f.startswith("--iters=")), 100)

    if "--roles" in flags:
        print_role_matrix()
        return

    project_id = os.getenv("MOSS_PROJECT_ID")
    project_key = os.getenv("MOSS_PROJECT_KEY")
    if not project_id or not project_key:
        raise SystemExit(f"Missing MOSS_PROJECT_ID / MOSS_PROJECT_KEY in {ENV_PATH}")

    client = MossClient(project_id, project_key)
    print(f"Loading Moss index '{INDEX}' into memory ...")
    t0 = time.perf_counter()
    try:
        await client.load_index(INDEX)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Could not load index '{INDEX}': {exc}\n"
            "Did you build it?  Run:  python3 create_index.py"
        )
    load_ms = (time.perf_counter() - t0) * 1000.0
    print(f"Index loaded in {load_ms:.1f} ms (one-time cost; queries are in-process after this).")

    # Warm-up: the first query lazily loads the embedding model and spins up the
    # query thread pool. There is NO result cache in Moss — the speedup on
    # repeated queries is this warmth (embedding model + thread pool + CPU/memory
    # locality), so we pay it once here and discard the measurement. We warm the
    # real Tier-1 shape (alpha=0 WITH a metadata filter), since the filtered path
    # is what every dose query actually hits.
    _WARMUP_FILTER = {"$and": [
        {"field": "drug", "condition": {"$eq": "EPINEPHRINE (1:1,000)"}},
        {"field": "patient_type", "condition": {"$eq": "adult"}},
    ]}

    async def _warm(label: str) -> None:
        try:
            _, ms = await _timed_query(
                client, "EPINEPHRINE (1:1,000)",
                QueryOptions(top_k=1, alpha=0, filter=_WARMUP_FILTER),
            )
            print(f"Warm-up query ({label}): {ms:.3f} ms")
        except Exception:  # noqa: BLE001
            pass

    await _warm("startup")

    # Offline proof: load_index above is the ONLY networked step. Pause here so
    # you can disable wifi, then confirm every query below still works.
    if pause:
        print("\n" + "*" * 64)
        print("*  Index is loaded. TURN OFF WIFI NOW.")
        print("*  Then press Enter — all queries after this must run with NO network.")
        print("*" * 64)
        try:
            input("  press Enter when wifi is off > ")
        except (EOFError, KeyboardInterrupt):
            return
        # Re-warm AFTER the idle pause: sitting at the input() prompt while you
        # toggle wifi lets the CPU/memory locality decay, which is exactly what
        # made the first post-pause query spike to ~30 ms. This pays it down so
        # your first real query is already at steady-state.
        await _warm("post-pause")
        print("  Continuing offline.\n")

    source = _load_source_by_page()
    role_table = roles_mod.load_role_table(PARSED_PATH)
    print(f"Role authorization: loaded for {len(role_table)} drug page(s).")

    if do_bench:
        await bench(client, DEMO_QUERIES if not args else [" ".join(args)], iters)
        return

    queries = DEMO_QUERIES if demo else ([" ".join(args)] if args else [])
    for q in queries:
        await run_query(client, source, q, role_table)

    if not queries:
        print("\nInteractive mode — type a colloquial query (add \"I'm an EMT\" to "
              "role-gate), or 'q' to quit.")
        while True:
            try:
                q = input("\nvigil> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"q", "quit", "exit"}:
                break
            if q:
                await run_query(client, source, q, role_table)


if __name__ == "__main__":
    asyncio.run(main())
