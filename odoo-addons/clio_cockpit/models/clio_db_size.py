import logging
import os
import subprocess

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

FILESTORE_BASE = '/var/lib/odoo/filestore'


def _pretty_size(size_bytes):
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024 ** 3:.1f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024 ** 2:.0f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


class ClioDbSize(models.Model):
    _name        = 'clio.db.size'
    _description = 'Clio — Databasstorlekar'
    _order       = 'total_size_bytes desc'
    _rec_name    = 'db_name'

    db_name               = fields.Char(string='Databas', required=True, index=True)
    pg_size_bytes         = fields.Integer(string='PostgreSQL (bytes)', default=0)
    pg_size_pretty        = fields.Char(string='PostgreSQL', default='—')
    filestore_size_bytes  = fields.Integer(string='Filestore (bytes)', default=0)
    filestore_size_pretty = fields.Char(string='Filestore', default='—')
    total_size_bytes      = fields.Integer(string='Totalt (bytes)', default=0)
    total_size_pretty     = fields.Char(string='Totalt', default='—')
    last_synced           = fields.Datetime(string='Senast synkad', copy=False)

    @api.model
    def action_sync_db_sizes(self):
        self.env.cr.execute("""
            SELECT datname, pg_database_size(datname)::bigint
            FROM pg_catalog.pg_database
            WHERE datistemplate = false
              AND datname NOT IN ('postgres')
            ORDER BY 2 DESC
        """)
        pg_sizes = dict(self.env.cr.fetchall())
        now = fields.Datetime.now()

        for db_name, pg_bytes in pg_sizes.items():
            fs_bytes = 0
            db_path = os.path.join(FILESTORE_BASE, db_name)
            if os.path.isdir(db_path):
                try:
                    r = subprocess.run(
                        ['du', '-sb', db_path],
                        capture_output=True, text=True, timeout=30,
                    )
                    if r.returncode == 0:
                        fs_bytes = int(r.stdout.split()[0])
                except Exception as exc:
                    _logger.warning('Filestore du failed for %s: %s', db_name, exc)

            total = pg_bytes + fs_bytes
            vals = {
                'pg_size_bytes':         pg_bytes,
                'pg_size_pretty':        _pretty_size(pg_bytes),
                'filestore_size_bytes':  fs_bytes,
                'filestore_size_pretty': _pretty_size(fs_bytes) if fs_bytes else '—',
                'total_size_bytes':      total,
                'total_size_pretty':     _pretty_size(total),
                'last_synced':           now,
            }
            existing = self.search([('db_name', '=', db_name)], limit=1)
            if existing:
                existing.write(vals)
            else:
                vals['db_name'] = db_name
                self.create(vals)

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def action_sync_and_open(self):
        self.action_sync_db_sizes()
        return {
            'type':      'ir.actions.act_window',
            'name':      'Databasstorlekar',
            'res_model': 'clio.db.size',
            'view_mode': 'list',
            'view_id':   self.env.ref('clio_cockpit.view_clio_db_size_list').id,
        }
