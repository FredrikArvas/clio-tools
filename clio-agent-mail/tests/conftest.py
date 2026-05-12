"""
conftest.py — testmiljö för clio-agent-mail.

1. Skapar en temporär SQLite-databas med rätt schema.
2. Lägger till clio-tools-roten i sys.path (behövs för clio_access-modulen).
"""
import os
import sys
import pytest
from pathlib import Path

# clio-tools root (../../) behövs för clio_access, clio_core m.fl.
CLIO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(CLIO_ROOT))
sys.path.insert(0, str(Path(__file__).parent.parent))

import state


@pytest.fixture(autouse=True, scope="session")
def init_test_db(tmp_path_factory):
    """Initierar en temporär SQLite-databas och pekar state-modulen dit."""
    db_path = tmp_path_factory.mktemp("db") / "state_test.db"
    state.init_db(db_path=db_path)
    original = state.DB_PATH
    state.DB_PATH = db_path
    yield db_path
    state.DB_PATH = original
