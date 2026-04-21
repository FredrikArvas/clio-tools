"""Entrypoint för clio-agent-odoo — kan anropas direkt eller via clio.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent import main

if __name__ == '__main__':
    main()
