"""
reindex_vigil_research.py
Raderar vigil_research-kollektionen och re-indexerar alla klara körningar (done/*.state.json).

Kör från clio-tools-roten:
    python3 clio-research/reindex_vigil_research.py
"""

import json
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env", override=True)
load_dotenv(BASE_DIR / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reindex")

DONE_DIR = BASE_DIR / "done"
COLLECTION_NAME = "vigil_research"


def reset_collection(client, VectorParams, Distance, vector_size: int) -> None:
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
        logger.info("Raderade kollektionen %s", COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    logger.info("Skapade kollektionen %s (dim=%d)", COLLECTION_NAME, vector_size)


def main() -> None:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
    except ImportError:
        logger.error("qdrant-client ej installerat")
        sys.exit(1)

    import qdrant_indexer as qi
    from embedder import VECTOR_SIZE

    client = QdrantClient(url=f"http://localhost:{6333}", check_compatibility=False)
    reset_collection(client, VectorParams, Distance, VECTOR_SIZE)

    state_files = sorted(DONE_DIR.glob("*.state.json"))
    if not state_files:
        logger.warning("Inga state-filer i %s", DONE_DIR)
        return

    logger.info("Hittade %d körningar att re-indexera", len(state_files))

    ok = 0
    for state_file in state_files:
        run_id = state_file.stem.replace(".state", "")
        report_path = DONE_DIR / f"{run_id}.md"

        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Kunde inte läsa %s: %s", state_file.name, e)
            continue

        sources = state.get("sources", [])
        protocol_id = state.get("protocol_id", run_id)

        protocol = {
            "protocol_id": protocol_id,
            "question": {"natural_language": state.get("question", protocol_id)},
            "created": state.get("started", ""),
        }

        if not report_path.exists():
            logger.warning("%s: rapport saknas (%s) — hoppar över", run_id, report_path.name)
            continue

        logger.info("Indexerar %s (%d källor) ...", run_id, len(sources))
        try:
            qi.index_report(protocol, sources, report_path, run_id)
            ok += 1
        except Exception as e:
            logger.error("%s: indexering misslyckades: %s", run_id, e)

    logger.info("Klart. %d/%d körningar indexerade.", ok, len(state_files))


if __name__ == "__main__":
    main()
