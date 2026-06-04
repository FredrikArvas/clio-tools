from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeClioNccProject(TransactionCase):
    """Smoke test — clio_ncc_project."""

    def setUp(self):
        super().setUp()
        self.model = self.env["clio.ncc.project"]

    def test_model_registered(self):
        self.assertIn("clio.ncc.project", self.env)

    def test_create_minimal(self):
        p = self.model.create({"name": "Testprojekt"})
        self.assertTrue(p.id)
        self.assertEqual(p.name, "Testprojekt")

    def test_create_full(self):
        p = self.model.create({
            "nr": "42",
            "sfar": "tech",
            "kodord": "testkod",
            "name": "Fullständigt projekt",
            "ncc_ok": True,
            "status_raw": "aktiv",
        })
        self.assertTrue(p.ncc_ok)
        self.assertEqual(p.kodord, "testkod")

    def test_name_required(self):
        with self.assertRaises(Exception):
            self.model.create({"kodord": "saknar_namn"})

    def test_order_by_nr(self):
        self.model.create({"nr": "10", "name": "B"})
        self.model.create({"nr": "05", "name": "A"})
        recs = self.model.search([("name", "in", ["A", "B"])])
        self.assertEqual(recs[0].nr, "05")
