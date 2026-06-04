from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeSsfLok(TransactionCase):
    """Smoke test — ssf_lok: fee_report och fee_report_value."""

    def setUp(self):
        super().setUp()
        self.Report = self.env["ssf.fee.report"]
        self.Value = self.env["ssf.fee.report.value"]

    def test_models_registered(self):
        self.assertIn("ssf.fee.report", self.env)
        self.assertIn("ssf.fee.report.value", self.env)

    def test_create_report(self):
        r = self.Report.create({
            "ssfta_id": 1001,
            "report_date": "2024-01-01",
            "report_amount": 5000.0,
            "paid_amount": 4500.0,
        })
        self.assertTrue(r.id)
        self.assertAlmostEqual(r.claim, 500.0)

    def test_compute_claim(self):
        r = self.Report.create({
            "report_amount": 10000.0,
            "paid_amount": 7500.0,
        })
        self.assertAlmostEqual(r.claim, 2500.0)

    def test_create_report_value(self):
        r = self.Report.create({"report_amount": 1000.0})
        v = self.Value.create({
            "fee_report_id": r.id,
            "district_name": "Stockholms SF",
            "amount": 250.0,
        })
        self.assertTrue(v.id)
        self.assertEqual(v.fee_report_id.id, r.id)
