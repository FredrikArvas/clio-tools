"""
clio_event_log.py — Odoo-modell för clio-agent-mail händelselogg

Synkas från SQLite events.db via trigger-baserad worker (events_db.py).
Varje rad representerar ett inkommande SSF-mail och dess utfall i
intent-klassificeringspipelinen.
"""

from odoo import models, fields, api


class ClioEventLog(models.Model):
    _name = 'clio.event.log'
    _description = 'Clio — Händelselogg (mail-klassificering)'
    _order = 'event_timestamp desc'
    _rec_name = 'display_name'

    # ── Identitet ─────────────────────────────────────────────────────────────
    sqlite_id = fields.Integer(
        string='SQLite ID',
        index=True,
        help='Primärnyckel från events.db — används för deduplicering vid synk.',
    )
    display_name = fields.Char(
        string='Händelse',
        compute='_compute_display_name',
        store=True,
    )

    # ── Tidsstämpel ───────────────────────────────────────────────────────────
    event_timestamp = fields.Datetime(
        string='Tidpunkt',
        required=True,
        index=True,
    )

    # ── Avsändare och ämne ────────────────────────────────────────────────────
    sender = fields.Char(string='Avsändare', required=True, index=True)
    subject = fields.Char(string='Ämne')

    # ── Klassificering ────────────────────────────────────────────────────────
    klassificering = fields.Selection(
        selection=[
            ('read',        'Läs'),
            ('write',       'Skriv'),
            ('execute',     'Utföra'),
            ('communicate', 'Kommunikation'),
            ('destructive', 'Destruktiv'),
            ('unclear',     'Oklar'),
            ('',            '—'),
        ],
        string='Intention',
        default='',
    )

    utfall = fields.Selection(
        selection=[
            ('allowed', 'Tillåten'),
            ('blocked', 'Blockerad'),
            ('error',   'Fel'),
        ],
        string='Utfall',
        required=True,
        index=True,
    )

    pii_risk = fields.Selection(
        selection=[
            ('none',   'Ingen'),
            ('low',    'Låg'),
            ('medium', 'Medel'),
            ('high',   'Hög'),
        ],
        string='PII-risk',
        default='none',
    )

    block_reason = fields.Text(string='Blockeringsorsak')

    # ── Synk-status ───────────────────────────────────────────────────────────
    synced_from_sqlite = fields.Boolean(
        string='Synkad från SQLite',
        default=True,
        help='True om raden skapades via events_db-synk, False om manuellt.',
    )

    # ── Compute ───────────────────────────────────────────────────────────────
    @api.depends('sender', 'subject', 'utfall')
    def _compute_display_name(self):
        utfall_labels = {
            'allowed': '✅',
            'blocked': '⛔',
            'error':   '⚠️',
        }
        for rec in self:
            icon = utfall_labels.get(rec.utfall, '')
            sender_short = (rec.sender or '').split('@')[0]
            subject_short = (rec.subject or '')[:40]
            rec.display_name = f"{icon} {sender_short} — {subject_short}"

    # ── Synk-hjälp: upsert via sqlite_id ─────────────────────────────────────
    @api.model
    def sync_from_sqlite(self, vals: dict) -> 'ClioEventLog':
        """
        Skapar en ny rad om sqlite_id inte finns, annars ingen-op.

        Anropas av odoo_sync_fn i clio-agent-mail via XML-RPC.
        vals-dict matchar events.db-schema:
          id, timestamp, sender, subject, klassificering,
          utfall, pii_risk, block_reason
        """
        sqlite_id = vals.get('id')
        if sqlite_id:
            existing = self.search([('sqlite_id', '=', sqlite_id)], limit=1)
            if existing:
                return existing

        # Parsa ISO-tidsstämpel → Odoo Datetime
        ts_raw = vals.get('timestamp', '')
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ts_raw)
            dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            dt_utc = fields.Datetime.now()

        return self.create({
            'sqlite_id':          sqlite_id or 0,
            'event_timestamp':    dt_utc,
            'sender':             vals.get('sender', ''),
            'subject':            vals.get('subject', ''),
            'klassificering':     vals.get('klassificering', '') or '',
            'utfall':             vals.get('utfall', 'error'),
            'pii_risk':           vals.get('pii_risk', 'none') or 'none',
            'block_reason':       vals.get('block_reason') or False,
            'synced_from_sqlite': True,
        })
