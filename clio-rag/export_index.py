"""
Exporterar shareable chunks från Qdrant till JSON-fil (ADD v1.0 §5, steg 6).

Inkluderar: alla fält utom loc_local_path (inte dela interna sökvägar).
Filtrerar: shareable == True.

Körning:
  python export_index.py
  python export_index.py --out mitt_index.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client.models import Filter, FieldCondition, MatchValue

import config
from config import COLLECTION_NAME, EXPORT_PATH, get_qdrant_client

load_dotenv()

# Fält som aldrig ska exporteras (lokala sökvägar, interna detaljer)
EXCLUDED_KEYS = {"loc_local_path", "loc_checksum_sha256"}


def scroll_shareable_chunks(client) -> list[dict]:
    """Hämtar alla chunks med ext_shareable == True från Qdrant."""
    results: list[dict] = []
    offset = None
    filt = Filter(must=[
        FieldCondition(key="ext_shareable", match=MatchValue(value=True))
    ])

    while True:
        batch, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=filt,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in batch:
            clean = {k: v for k, v in point.payload.items() if k not in EXCLUDED_KEYS}
            clean["_point_id"] = str(point.id)
            results.append(clean)
        if next_offset is None:
            break
        offset = next_offset

    return results


def export_index(out_path: Path) -> None:
    client = get_qdrant_client()

    print("[export] Hämtar shareable chunks från Qdrant …")
    chunks = scroll_shareable_chunks(client)

    if not chunks:
        print("[export] Inga shareable chunks hittades. Är clio_books indexerad?")
        return

    index = {
        "schema_version": config.SCHEMA_VERSION,
        "exported_at":    datetime.now(timezone.utc).isoformat(),
        "collection":     COLLECTION_NAME,
        "chunk_count":    len(chunks),
        "chunks":         chunks,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    size_kb = out_path.stat().st_size // 1024
    print(f"[export] Exporterade {len(chunks)} chunks → {out_path} ({size_kb} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="clio-rag: exportera shareable index")
    parser.add_argument("--out", type=Path, default=EXPORT_PATH,
                        help=f"Utdatafil (default: {EXPORT_PATH})")
    args = parser.parse_args()
    export_index(args.out)


if __name__ == "__main__":
    main()
