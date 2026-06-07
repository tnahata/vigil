"""Build the Vigil Moss index from the chunked protocol data.

Reads ../unsiloed-test/chunks.json (produced by unsiloed-test/chunk.py) and
creates a single Moss index named by MOSS_INDEX_NAME.  Aligned with the Moss
indexing guide: https://docs.moss.dev/docs/integrate/indexing-data

    python3 create_index.py [path/to/chunks.json] [--dry-run] [--verify]

Credentials are read from moss-test/.env (MOSS_PROJECT_ID / MOSS_PROJECT_KEY).

Flags:
  --dry-run   Load + validate + print stats and the quality gate, but do NOT
              contact Moss. Works without credentials — use it to see exactly
              what would be indexed.
  --verify    After creating the index, run a Tier-1 (alpha=0, keyword) and a
              Tier-2 (alpha=0.6, hybrid) sample query and print the top hits,
              so you can confirm alpha direction before going live
              (CLAUDE.md: "VERIFY alpha direction").

The script refuses to push if the quality gate fails (markdown boilerplate or
duplicate ids in the embedded text) — a bad chunks.json never reaches Moss.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from moss import DocumentInfo, MossClient, MutationOptions, QueryOptions

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CHUNKS_PATH = BASE_DIR.parent / "unsiloed-test" / "chunks.json"
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

DEFAULT_INDEX_NAME = "vigil-protocol"
DEFAULT_MODEL_ID = "moss-minilm"


def _load_chunks(path: Path) -> list[DocumentInfo]:
    if not path.exists():
        raise FileNotFoundError(f"Chunks file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("chunks.json must be a JSON array.")

    docs: list[DocumentInfo] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        doc_id = entry.get("id")
        text = entry.get("text")
        if not doc_id or not text:
            continue
        meta = entry.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        # Moss metadata values must be strings; convert None → "".
        str_meta = {str(k): ("" if v is None else str(v)) for k, v in meta.items()}
        docs.append(DocumentInfo(id=str(doc_id), text=str(text), metadata=str_meta))

    if not docs:
        raise ValueError("No valid documents loaded from chunks.json.")

    return docs


def _report(docs: list[DocumentInfo]) -> bool:
    """Print index-build stats + run the quality gate. Returns True if clean."""
    tok_sizes = [len(d.text) // 4 for d in docs]
    bands = {"<50": 0, "50-199": 0, "200-500": 0, ">500": 0}
    for t in tok_sizes:
        if t < 50:      bands["<50"] += 1
        elif t < 200:   bands["50-199"] += 1
        elif t <= 500:  bands["200-500"] += 1
        else:           bands[">500"] += 1

    by_type: dict[str, int] = {}
    for d in docs:
        rt = d.metadata.get("record_type", "?")
        by_type[rt] = by_type.get(rt, 0) + 1

    print(f"\n{'=' * 64}")
    print("INDEX BUILD PLAN")
    print(f"{'=' * 64}")
    print(f"Documents            : {len(docs)}")
    print(f"By record_type       : {by_type}")
    print(f"Token sizes (est)    : min={min(tok_sizes)}  avg={sum(tok_sizes)//len(tok_sizes)}  max={max(tok_sizes)}")
    print(f"Token histogram      : {bands}  (Moss target band: 200-500)")

    dirty = [d.id for d in docs
             if "**" in d.text or "<br>" in d.text or ".." in d.text]
    dup = len(docs) - len({d.id for d in docs})

    print(f"\n{'-' * 64}")
    print("QUALITY GATE")
    print(f"{'-' * 64}")
    print(f"  duplicate ids      : {dup}")
    print(f"  markdown-leak rows : {len(dirty)}")
    clean = not dirty and dup == 0
    if dirty:
        print("  FAIL — boilerplate in:", ", ".join(dirty[:10]))
    elif dup:
        print("  FAIL — duplicate document ids present")
    else:
        print("  PASS — embedded text is clean")
    return clean


async def _verify_alpha(client: MossClient, index_name: str) -> None:
    """Run a keyword (alpha=0) and a hybrid (alpha=0.6) sample query."""
    await client.load_index(index_name)
    print(f"\n{'=' * 64}")
    print("ALPHA VERIFICATION")
    print(f"{'=' * 64}")

    samples = [
        ("Tier-1 keyword (alpha=0)", "EPINEPHRINE (1:1,000)", QueryOptions(top_k=3, alpha=0)),
        ("Tier-2 hybrid (alpha=0.6)", "patient's throat is swelling, severe allergic reaction",
         QueryOptions(top_k=3, alpha=0.6)),
    ]
    for label, q, opts in samples:
        print(f"\n{label}  query={q!r}")
        try:
            result = await client.query(index_name, q, opts)
            for i, doc in enumerate(getattr(result, "docs", []) or [], 1):
                score = getattr(doc, "score", None)
                score_s = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
                print(f"  {i}. {doc.id:50} score={score_s}")
        except Exception as exc:  # noqa: BLE001
            print(f"  query failed: {exc}")


async def build_index(chunks_path: Path, dry_run: bool, verify: bool) -> None:
    index_name = os.getenv("MOSS_INDEX_NAME", DEFAULT_INDEX_NAME)
    model_id = os.getenv("MOSS_MODEL_ID", DEFAULT_MODEL_ID)

    docs = _load_chunks(chunks_path)
    print(f"Loaded {len(docs)} documents from {chunks_path}")
    clean = _report(docs)

    if not clean:
        raise SystemExit("\nRefusing to index: quality gate failed. Fix chunks.json first.")

    if dry_run:
        print("\n[--dry-run] Skipping Moss push. Index plan above is clean and ready.")
        return

    project_id = os.getenv("MOSS_PROJECT_ID")
    project_key = os.getenv("MOSS_PROJECT_KEY")
    missing = [k for k, v in {"MOSS_PROJECT_ID": project_id, "MOSS_PROJECT_KEY": project_key}.items() if not v]
    if missing:
        raise OSError(
            "Missing required env vars: " + ", ".join(missing)
            + f"\nSet them in {ENV_PATH} (or use --dry-run to validate offline)."
        )

    client = MossClient(project_id, project_key)
    print(f"\nCreating Moss index '{index_name}' (model={model_id}) ...")
    try:
        result = await client.create_index(index_name, docs, model_id)
        print(
            f"Done — job: {result.job_id}, index: {result.index_name}, docs: {result.doc_count}"
        )
    except Exception as exc:  # noqa: BLE001
        # Re-runnable: if the index already exists, upsert the docs instead so
        # you can rebuild after tweaking chunks.json without deleting first.
        if "exist" in str(exc).lower() or "409" in str(exc):
            print("  index already exists — upserting docs instead ...")
            await client.add_docs(index_name, docs, MutationOptions(upsert=True))
            print(f"  upserted {len(docs)} docs into '{index_name}'")
        else:
            raise

    if verify:
        await _verify_alpha(client, index_name)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    path = Path(args[0]) if args else DEFAULT_CHUNKS_PATH
    asyncio.run(
        build_index(path, dry_run="--dry-run" in flags, verify="--verify" in flags)
    )
