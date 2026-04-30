"""config.py — Centraliserad konfiguration för clio-uap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent

# Ladda .env
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT_DIR / ".env", override=True)
    load_dotenv(_BASE_DIR / ".env", override=True)
except ImportError:
    pass

# Lägg till clio_odoo i sys.path
for _p in [str(_ROOT_DIR), str(_BASE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Odoo
ODOO_URL      = os.getenv("ODOO_URL", "")
ODOO_DB       = os.getenv("ODOO_DB", "aiab")
ODOO_USER     = os.getenv("ODOO_USER", "")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")

# Qdrant
QDRANT_HOST       = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT       = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = "vigil_uap"

# Neo4j
NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# Claude
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL       = "claude-sonnet-4-6"

# OpenAI (för embeddings)
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL    = "text-embedding-3-small"

# Video-analys
VIDEO_FRAMES_PER_SEC       = float(os.getenv("UAP_FRAMES_PER_SEC", "2"))
VIDEO_VISION_MODEL         = os.getenv("UAP_VISION_MODEL", "claude-sonnet-4-6")
VIDEO_CONFIDENCE_THRESHOLD = float(os.getenv("UAP_CONFIDENCE_THRESHOLD", "0.7"))

# Källmapp för UAP-data
UAP_DATA_PATH = Path(os.getenv(
    "UAP_DATA_PATH",
    r"C:\Users\fredr\Dropbox\projekt\UAP\UAP Research project",
))
