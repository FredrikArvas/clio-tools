"""
push_odoo.py -- Platshallare for Odoo-integration (lager 3).

Modell: bmc.canvas
  - many2one till res.partner (valfritt)
  - many2one till project.project (valfritt)
  - 9 block som Text-falt
  - version: as-is / to-be

Byggs i separat Claude Code-session nar lager 2 ar driftsatt.
Se NCC #bmctools for roadmap.
"""


def push(session: dict, db: str = 'aiab', dry_run: bool = False) -> None:
    raise NotImplementedError(
        'Odoo-integration (lager 3) ar annu inte byggd. '
        'Se NCC #bmctools: https://notion.so/35867666d98a81e180ebc2bf0624da5c'
    )
