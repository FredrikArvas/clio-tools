from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeClioJob(TransactionCase):
    """Smoke test — clio_job: article, profile, match + res.partner-fält."""

    def setUp(self):
        super().setUp()
        self.Article = self.env["clio.job.article"]
        self.Profile = self.env["clio.job.profile"]
        self.Match = self.env["clio.job.match"]

    def test_models_registered(self):
        for m in ["clio.job.article", "clio.job.profile", "clio.job.match"]:
            self.assertIn(m, self.env)

    def test_partner_has_job_profile_field(self):
        partner = self.env["res.partner"].create({"name": "Jobbtest"})
        self.assertTrue(hasattr(partner, "clio_job_profile_ids"))

    def test_create_article(self):
        art = self.Article.create({
            "article_id": "abc123hash",
            "title": "Testtitel",
            "source": "TestFeed",
        })
        self.assertTrue(art.id)
        self.assertEqual(art.article_id, "abc123hash")

    def test_article_id_required(self):
        with self.assertRaises(Exception):
            self.Article.create({"title": "Utan article_id"})

    def test_create_profile(self):
        partner = self.env["res.partner"].create({"name": "Kandidat"})
        prof = self.Profile.create({"partner_id": partner.id})
        self.assertTrue(prof.id)
        self.assertEqual(prof.partner_id.name, "Kandidat")

    def test_create_match(self):
        partner = self.env["res.partner"].create({"name": "MatchKandidat"})
        prof = self.Profile.create({"partner_id": partner.id})
        match = self.Match.create({
            "profile_id": prof.id,
            "article_title": "Matchad artikel",
            "match_score": 85,
        })
        self.assertTrue(match.id)
        self.assertEqual(match.match_score, 85)
