from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeClioMailAdmin(TransactionCase):
    """Smoke test — clio_mail_admin: TransientModel-registrering."""

    def test_models_registered(self):
        """Alla mail admin-modeller ska vara registrerade."""
        self.assertIn("clio.mail.admin", self.env)
        self.assertIn("clio.waiting.line", self.env)

    def test_mail_admin_can_instantiate(self):
        """TransientModel ska gå att skapa utan fel."""
        admin = self.env["clio.mail.admin"].create({})
        self.assertTrue(admin.id)

    def test_reopen_returns_action(self):
        """_reopen() ska returnera ett ir.actions.act_window-dict."""
        admin = self.env["clio.mail.admin"].create({})
        action = admin._reopen()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "clio.mail.admin")
        self.assertEqual(action["res_id"], admin.id)
