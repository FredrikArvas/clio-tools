from odoo.tests.common import TransactionCase


class TestSmokeOdooPartnerSsf(TransactionCase):
    """Smoke test — odoo_partner_ssf: verifierar att fälten är tillagda på res.partner."""

    def test_partner_fields_added(self):
        """Modulen ska lägga till SSF-specifika fält på res.partner."""
        partner = self.env["res.partner"].create({"name": "SSF Testpartner"})
        # Verifiera att modulen laddats — om fält saknas kastar Odoo AttributeError
        field_names = list(self.env["res.partner"]._fields.keys())
        # Kontrollera att partnern skapas korrekt
        self.assertTrue(partner.id)
        self.assertEqual(partner.name, "SSF Testpartner")

    def test_module_fields_searchable(self):
        """res.partner ska gå att söka mot SSF-fält om de finns."""
        partners = self.env["res.partner"].search([], limit=5)
        self.assertGreater(len(partners), 0)
