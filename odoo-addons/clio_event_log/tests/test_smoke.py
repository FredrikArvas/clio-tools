from odoo.tests.common import TransactionCase


class TestSmokeClioEventLog(TransactionCase):
    """Smoke test — clio_event_log: modell, CRUD, compute-fält."""

    def setUp(self):
        super().setUp()
        self.model = self.env["clio.event.log"]

    def test_model_registered(self):
        self.assertIn("clio.event.log", self.env)

    def test_create_minimal(self):
        record = self.model.create({
            "event_timestamp": "2024-01-01 12:00:00",
            "sender": "test@example.com",
            "utfall": "allowed",
        })
        self.assertTrue(record.id)
        self.assertEqual(record.sender, "test@example.com")

    def test_display_name_computed(self):
        record = self.model.create({
            "event_timestamp": "2024-01-01 12:00:00",
            "sender": "clio@example.com",
            "subject": "Testämne",
            "utfall": "allowed",
        })
        self.assertIn("clio", record.display_name)
        self.assertIn("✅", record.display_name)

    def test_sync_from_sqlite_creates(self):
        vals = {
            "id": 9999,
            "timestamp": "2024-01-01T12:00:00",
            "sender": "sync@example.com",
            "subject": "Sync-test",
            "utfall": "blocked",
            "pii_risk": "low",
        }
        record = self.model.sync_from_sqlite(vals)
        self.assertTrue(record.id)
        self.assertEqual(record.sqlite_id, 9999)

    def test_sync_from_sqlite_idempotent(self):
        vals = {
            "id": 8888,
            "timestamp": "2024-01-01T12:00:00",
            "sender": "idempotent@example.com",
            "utfall": "allowed",
        }
        r1 = self.model.sync_from_sqlite(vals)
        r2 = self.model.sync_from_sqlite(vals)
        self.assertEqual(r1.id, r2.id)
