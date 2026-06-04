from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeSsfPayments(TransactionCase):
    """Smoke test — ssf_payments: payment och payment_entry."""

    def setUp(self):
        super().setUp()
        self.Payment = self.env["ssf.payment"]
        self.Entry = self.env["ssf.payment.entry"]

    def test_models_registered(self):
        self.assertIn("ssf.payment", self.env)
        self.assertIn("ssf.payment.entry", self.env)

    def test_create_payment(self):
        p = self.Payment.create({
            "ssfta_id": 2001,
            "order_id": "ORD-2001",
            "date": "2024-03-01",
            "amount": 1200.0,
            "status": "paid",
        })
        self.assertTrue(p.id)
        self.assertEqual(p.order_id, "ORD-2001")

    def test_create_payment_entry(self):
        payment = self.Payment.create({
            "ssfta_id": 2002,
            "amount": 500.0,
        })
        entry = self.Entry.create({
            "payment_id": payment.id,
            "entry_id": 3001,
            "amount": 500.0,
        })
        self.assertTrue(entry.id)
        self.assertEqual(entry.payment_id.id, payment.id)

    def test_entry_cascade_delete(self):
        payment = self.Payment.create({"ssfta_id": 2003})
        entry = self.Entry.create({"payment_id": payment.id})
        entry_id = entry.id
        payment.unlink()
        self.assertFalse(self.Entry.search([("id", "=", entry_id)]))
