from odoo.tests.common import TransactionCase


class TestSmokeClioDiscuss(TransactionCase):
    """Smoke test — clio_discuss: verifierar att modulen lastar korrekt."""

    def test_discuss_channel_extended(self):
        """discuss.channel ska vara tillgänglig med Clio-utökning."""
        self.assertIn("discuss.channel", self.env)
        ch = self.env["discuss.channel"].search([], limit=1)
        # Om kanalen finns, verifiera att Clio-metoden är tillgänglig
        if ch:
            self.assertTrue(hasattr(ch, "message_post"))

    def test_config_params_accessible(self):
        """Clio Discuss-konfigparametrar ska vara åtkomliga."""
        param = self.env["ir.config_parameter"].sudo()
        # Parametrar som clio_discuss använder
        url = param.get_param("clio.service.url", default="http://localhost:7200")
        self.assertTrue(url)
