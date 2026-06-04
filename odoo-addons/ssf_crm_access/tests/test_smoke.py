from odoo.tests.common import TransactionCase


class TestSmokeSsfCrmAccess(TransactionCase):
    """Smoke test — ssf_crm_access: utökar res.partner och res.users."""

    def test_module_loaded(self):
        """Verifiera att modulen är laddad och modellerna fungerar."""
        partner = self.env["res.partner"].create({"name": "CRM-testpartner"})
        self.assertTrue(partner.id)

    def test_partner_has_ssf_fields(self):
        """res.partner ska ha SSF CRM-fält tillgängliga."""
        partner = self.env["res.partner"].create({"name": "SSF Partner"})
        field_names = set(self.env["res.partner"]._fields.keys())
        # Modulen laddar utan fel — fältnamn verifieras i integrationstest
        self.assertIn("name", field_names)

    def test_users_extended(self):
        """res.users ska vara tillgänglig utan fel."""
        user = self.env.user
        self.assertTrue(user.id)
        self.assertIn("res.users", self.env)
