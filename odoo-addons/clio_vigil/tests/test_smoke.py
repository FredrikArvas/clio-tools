from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeClioVigil(TransactionCase):
    """Smoke test — clio_vigil: keyword, item, source, subscriber."""

    def setUp(self):
        super().setUp()
        self.Keyword = self.env["clio.vigil.keyword"]
        self.Item = self.env["clio.vigil.item"]
        self.Source = self.env["clio.vigil.source"]
        self.Subscriber = self.env["clio.vigil.subscriber"]

    def test_models_registered(self):
        for model in [
            "clio.vigil.keyword", "clio.vigil.item", "clio.vigil.source",
            "clio.vigil.subscriber", "clio.vigil.pipeline",
        ]:
            self.assertIn(model, self.env)

    def test_create_keyword(self):
        kw = self.Keyword.create({"keyword": "ufo", "domain": "ufo"})
        self.assertTrue(kw.id)
        self.assertEqual(kw.keyword, "ufo")

    def test_keyword_required(self):
        with self.assertRaises(Exception):
            self.Keyword.create({})

    def test_create_item(self):
        item = self.Item.create({
            "url": "https://example.com/artikel",
            "title": "Testartikel",
            "domain": "ufo",
            "source_type": "rss",
        })
        self.assertTrue(item.id)

    def test_item_url_required(self):
        with self.assertRaises(Exception):
            self.Item.create({"title": "Utan URL"})

    def test_create_source(self):
        src = self.Source.create({
            "name": "Testkälla",
            "source_type": "rss",
            "url": "https://example.com/feed.xml",
        })
        self.assertTrue(src.id)

    def test_create_subscriber(self):
        partner = self.env["res.partner"].create({"name": "Prenumerant"})
        sub = self.Subscriber.create({"partner_id": partner.id})
        self.assertTrue(sub.id)
