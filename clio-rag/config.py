"""
Konfiguration för clio-rag MVP (ADD v1.0 §3, §8).

Läser inställningar från miljövariabler / .env.
Exporterar hjälpfunktioner: get_qdrant_client(), create_collection(),
is_local_available().
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

# Sök .env i clio-rag/, annars ett steg upp (clio-tools/)
_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

# Notion — läses efter load_dotenv
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")

# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------
QDRANT_HOST      = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT      = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME      = "clio_books"
NCC_COLLECTION_NAME  = "clio_ncc"

# Notion-sida med alla NCC:er som child-pages
NCC_PARENT_PAGE_ID   = "33467666d98a816db2c0d30cb97206a3"  # Clio Context — Mall & Projektöversikt

# ---------------------------------------------------------------------------
# Modeller
# ---------------------------------------------------------------------------
EMBEDDING_MODEL  = "text-embedding-3-small"
EMBEDDING_DIM    = 1536
LLM_MODEL        = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Sökvägar
# ---------------------------------------------------------------------------
# På EliteDesk (Ubuntu): WD4TB1 monteras t.ex. på /mnt/wd4tb1
# På Windows (dev): sätt CORPUS_PATH i .env till Dropbox-sökvägar
CORPUS_PATH      = Path(os.getenv("CORPUS_PATH", "/mnt/wd4tb1/clio-rag/corpus"))
LOCAL_DISK_MOUNT = Path(os.getenv("LOCAL_DISK_MOUNT", "/mnt/wd4tb1"))

# Export-fil (shareable index)
EXPORT_PATH      = Path(os.getenv("EXPORT_PATH", "clio_books_index_v1.json"))

# ---------------------------------------------------------------------------
# Kända böcker i MVP-korpuset
# Används av ingest.py för att matcha filnamn mot metadata.
# ---------------------------------------------------------------------------
BOOK_METADATA: dict[str, dict] = {
    # Corpus-namn (helg, WD4TB1)
    "ovillkorlig.pdf": {
        "title":            "Ovillkorlig",
        "author":           "Ulrika Arvas",
        "year":             2013,
        "publisher":        "AIAB",
        "copyright_status": "licensed",
        "access_origin":    "self_created",
        "shareable":        True,
    },
    # Dropbox-filnamn (dev/test)
    "ovillkorlig_311c.pdf": {
        "title":            "Ovillkorlig",
        "author":           "Ulrika Arvas",
        "year":             2013,
        "publisher":        "AIAB",
        "copyright_status": "licensed",
        "access_origin":    "self_created",
        "shareable":        True,
    },
    "egenanstallning.pdf": {
        "title":            "Egenanställning",
        "author":           "Fredrik Arvas",
        "year":             2013,
        "publisher":        "AIAB",
        "copyright_status": "licensed",
        "access_origin":    "self_created",
        "shareable":        True,
    },
    "egenanställning_2013.pdf": {
        "title":            "Egenanställning",
        "author":           "Fredrik Arvas",
        "year":             2013,
        "publisher":        "AIAB",
        "copyright_status": "licensed",
        "access_origin":    "self_created",
        "shareable":        True,
    },
    "mba_umbrella_companies.pdf": {
        "title":            "MBA-rapport: Umbrella Companies",
        "author":           "Fredrik Arvas",
        "year":             2012,
        "publisher":        "AIAB",
        "copyright_status": "licensed",
        "access_origin":    "self_created",
        "shareable":        True,
    },
    "fredrikarvas_umbrellacompanies_v.17.pdf": {
        "title":            "MBA-rapport: Umbrella Companies",
        "author":           "Fredrik Arvas",
        "year":             2012,
        "publisher":        "AIAB",
        "copyright_status": "licensed",
        "access_origin":    "self_created",
        "shareable":        True,
    },
}

# Schema-version — höj manuellt vid strukturändring
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def create_collection() -> None:
    """Skapar clio_books-collection om den inte redan finns."""
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"[config] Skapade collection: {COLLECTION_NAME} ({EMBEDDING_DIM} dim, cosine)")
    else:
        print(f"[config] Collection finns redan: {COLLECTION_NAME}")


def create_ncc_collection() -> None:
    """Skapar clio_ncc-collection om den inte redan finns."""
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if NCC_COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=NCC_COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"[config] Skapade collection: {NCC_COLLECTION_NAME} ({EMBEDDING_DIM} dim, cosine)")
    else:
        print(f"[config] Collection finns redan: {NCC_COLLECTION_NAME}")


def is_local_available() -> bool:
    """Returnerar True om WD4TB1 är monterad (lazy loading-kontroll)."""
    mount = LOCAL_DISK_MOUNT
    if not mount.exists():
        return False
    # På Linux: kontrollera att det faktiskt är en mountpoint
    try:
        return mount.is_mount()
    except (OSError, NotImplementedError):
        # Windows dev-läge: acceptera om mappen finns
        return mount.is_dir()


if __name__ == "__main__":
    create_collection()
