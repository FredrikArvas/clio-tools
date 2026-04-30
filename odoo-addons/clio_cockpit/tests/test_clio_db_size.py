# Kör: docker exec odoo-odoo-1 odoo --db_host=db --db_user=odoo --db_password=odoo
#       --test-enable --log-level=test --no-http -u clio_cockpit -d aiab --stop-after-init
from odoo.tests.common import TransactionCase


class TestClioDbSize(TransactionCase):

    def test_sync_creates_records(self):
        DbSize = self.env['clio.db.size']
        DbSize.action_sync_db_sizes()
        records = DbSize.search([])
        self.assertTrue(len(records) > 0, 'Inga poster skapades efter sync')
        for rec in records:
            self.assertGreater(rec.pg_size_bytes, 0,
                               f'{rec.db_name}: pg_size_bytes är noll')
            self.assertTrue(rec.pg_size_pretty,
                            f'{rec.db_name}: pg_size_pretty saknas')
            self.assertGreaterEqual(rec.total_size_bytes, rec.pg_size_bytes,
                                    f'{rec.db_name}: total < pg')

    def test_action_sync_and_open_returns_act_window(self):
        DbSize = self.env['clio.db.size']
        result = DbSize.action_sync_and_open()
        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'clio.db.size')
