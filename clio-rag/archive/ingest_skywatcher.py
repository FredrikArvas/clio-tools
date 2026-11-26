"""
Engångsskript: indexerar Skywatcher Discovery Framework PDF
till vigil_uap_docs-collection i Qdrant.

Skapar collection om den inte finns (1536-dim, cosine — matchar text-embedding-3-small).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config

# Patcha collection-namnet INNAN ingest.py importeras
COLLECTION = "vigil_uap_docs"
config.COLLECTION_NAME = COLLECTION

import ingest  # noqa: E402 — måste komma efter patch

from qdrant_client.models import Distance, VectorParams

PDF_PATH = Path("/tmp/skywatcher_discovery_framework.pdf")

if not PDF_PATH.exists():
    print(f"FEL: filen saknas: {PDF_PATH}")
    sys.exit(1)

# Skapa collection om den saknas
qdrant = config.get_qdrant_client()
existing = [c.name for c in qdrant.get_collections().collections]
if COLLECTION not in existing:
    qdrant.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=config.EMBEDDING_DIM, distance=Distance.COSINE),
    )
    print(f"[setup] Skapade collection: {COLLECTION} ({config.EMBEDDING_DIM} dim, cosine)")
else:
    print(f"[setup] Collection finns redan: {COLLECTION}")

# Sätt metadata i cache så _ask_rights inte frågar interaktivt
meta_cache = ingest._load_meta_cache()
key = PDF_PATH.name.lower()
if key not in meta_cache:
    meta_cache[key] = {
        "title":     "Skywatcher Discovery Framework",
        "author":    "Skywatcher",
        "year":      2024,
        "copyright": "all_rights_reserved",
        "access":    "open_access",
        "notes":     "Public UAP research paper — skywatcher.ai",
    }
    ingest._save_meta_cache(meta_cache)

n = ingest.ingest_pdf(PDF_PATH, force=False)
print(f"\n✅ Klart — {n} nya chunks indexerade i {COLLECTION}.")
