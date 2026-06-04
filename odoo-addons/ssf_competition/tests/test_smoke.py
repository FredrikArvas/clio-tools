from odoo.tests.common import TransactionCase


class TestSmokeSsfCompetition(TransactionCase):
    """Smoke test — ssf_competition: alla modeller registrerade + basic CRUD."""

    MODELS = [
        "ssf.competition", "ssf.season", "ssf.discipline", "ssf.sector",
        "ssf.comp.class", "ssf.cup", "ssf.event", "ssf.entry",
        "ssf.result", "ssf.result.list", "ssf.fis.competitor",
        "ssf.non.member", "ssf.iol.role", "ssf.person.sector",
        "ssf.comp.ccd",
    ]

    def test_all_models_registered(self):
        """Alla modeller ska vara registrerade i ORM."""
        for model in self.MODELS:
            self.assertIn(model, self.env, f"Modell saknas: {model}")

    def test_all_models_searchable(self):
        """Alla modeller ska gå att söka i utan fel."""
        for model in self.MODELS:
            result = self.env[model].search([], limit=1)
            # Ingen exception == OK

    def test_create_season(self):
        """ssf.season: skapar en säsong."""
        s = self.env["ssf.season"].create({"name": "2024/2025"})
        self.assertTrue(s.id)

    def test_create_discipline(self):
        d = self.env["ssf.discipline"].create({"name": "Slalom"})
        self.assertTrue(d.id)

    def test_create_sector(self):
        sec = self.env["ssf.sector"].create({"name": "Alpint", "code": "AL"})
        self.assertTrue(sec.id)

    def test_create_competition(self):
        comp = self.env["ssf.competition"].create({"name": "Testtävling 2024"})
        self.assertTrue(comp.id)

    def test_create_iol_role(self):
        partner = self.env["res.partner"].create({"name": "IOL-person"})
        org = self.env["res.partner"].create({"name": "IOL-org", "is_company": True})
        role = self.env["ssf.iol.role"].create({
            "person_id": partner.id,
            "organisation_id": org.id,
            "role_name": "Ordförande",
        })
        self.assertTrue(role.id)

    def test_create_non_member(self):
        nm = self.env["ssf.non.member"].create({
            "name": "Utländsk gäst",
        })
        self.assertTrue(nm.id)
