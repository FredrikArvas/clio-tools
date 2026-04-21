"""
clio_run_odoo.py
Launcher för clio-agent-odoo — Clio AI-assistent i Odoo Discuss.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

from clio_menu import (
    BackToMenu,
    GRN, YEL, GRY, BLD, NRM,
    clear,
    menu_select, menu_pause,
)

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key


_CHOICES = [
    "1.  Starta agenten              (lyssnar på port 8100)",
    "2.  Hälsokontroll               (GET /health)",
    "3.  Visa setup-instruktioner",
]

_SETUP_TEXT = """
  INSTALLATION — clio_discuss i Odoo
  ─────────────────────────────────────────────────────

  1. Kopiera addon till servern:
     scp -r odoo-addons/clio_discuss clioadmin@<server>:/opt/odoo/extra-addons/

  2. Installera i Odoo (DB: aiab):
     docker exec -it odoo-odoo-1 odoo -d aiab -i clio_discuss --stop-after-init

  3. Hämta Clio Bot-lösenordet:
     Odoo → Inställningar → Teknisk → Systemparametrar
     Sök: clio_discuss.bot_password  → kopiera värdet

  4. Skapa clio-agent-odoo/.env:
     Kopiera .env.example → .env och fyll i:
       ODOO_BOT_PASSWORD=<värdet från steg 3>
       CLIO_ODOO_SECRET=<valfri hemlighet, sätt samma i Odoo>

  5. Sätt CLIO_ODOO_SECRET i Odoo:
     Odoo → Inställningar → Teknisk → Systemparametrar
     Sök: clio_discuss.shared_secret → sätt samma värde

  6. Starta agenten (menyval 1) och testa i Odoo Discuss → #Clio
  ─────────────────────────────────────────────────────
"""


def run_odoo(tool: dict, state: dict) -> None:
    agent_run = ROOT / 'clio-agent-odoo' / 'run.py'

    while True:
        clear()
        print(f'\n{BLD}  clio-agent-odoo  —  Clio i Odoo Discuss{NRM}')
        print(f'{"─" * 56}\n')
        choice = menu_select('Välj:', _CHOICES)
        if choice is None:
            return
        mode = choice.split('.')[0].strip()

        if mode == '1':
            print(f'\n{"─" * 40}')
            print(f'{GRN}Startar clio-agent-odoo på port 8100...{NRM}')
            print(f'{GRY}Avbryt med Ctrl+C{NRM}\n')
            try:
                subprocess.run([sys.executable, str(agent_run)], text=True, errors='replace')
            except KeyboardInterrupt:
                print('\n(Stoppad av användaren)')

        elif mode == '2':
            import urllib.request
            import urllib.error
            print(f'\n{"─" * 40}')
            try:
                resp = urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=3)
                print(f'{GRN}Agenten svarar:{NRM} {resp.read().decode()}')
            except Exception as exc:
                print(f'{YEL}Agenten svarar inte:{NRM} {exc}')

        elif mode == '3':
            print(_SETUP_TEXT)

        menu_pause()
