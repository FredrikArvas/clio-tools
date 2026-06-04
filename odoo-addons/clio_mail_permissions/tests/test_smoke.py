from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeClioMailPermissions(TransactionCase):
    """Smoke test — clio_mail_permissions."""

    def setUp(self):
        super().setUp()
        self.model = self.env["clio.mail.permission"]

    def test_model_registered(self):
        self.assertIn("clio.mail.permission", self.env)

    def test_create_whitelisted(self):
        p = self.model.create({
            "email": "ok@example.com",
            "list_type": "whitelisted",
        })
        self.assertTrue(p.id)
        self.assertEqual(p.list_type, "whitelisted")

    def test_create_blacklisted(self):
        p = self.model.create({
            "email": "bad@example.com",
            "list_type": "blacklisted",
        })
        self.assertEqual(p.list_type, "blacklisted")

    def test_default_list_type(self):
        p = self.model.create({"email": "default@example.com"})
        self.assertEqual(p.list_type, "whitelisted")

    def test_email_required(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(Exception):
            self.model.create({"list_type": "whitelisted"})
