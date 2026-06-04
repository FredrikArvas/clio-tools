from odoo.tests.common import TransactionCase


class TestSmokeClioUap(TransactionCase):
    """Smoke test — clio_uap: encounter, source, witness, verification."""

    def setUp(self):
        super().setUp()
        self.Encounter = self.env["uap.encounter"]
        self.Source = self.env["uap.source"]
        self.Witness = self.env["uap.witness"]
        self.Verification = self.env["uap.verification"]

    def test_models_registered(self):
        for m in ["uap.encounter", "uap.source", "uap.witness", "uap.verification"]:
            self.assertIn(m, self.env)

    def test_create_encounter(self):
        enc = self.Encounter.create({"encounter_id": "SWE_TEST_0001"})
        self.assertTrue(enc.id)
        self.assertEqual(enc.encounter_id, "SWE_TEST_0001")
        self.assertTrue(enc.encounter_guid)  # default lambda

    def test_encounter_id_required(self):
        with self.assertRaises(Exception):
            self.Encounter.create({"title_en": "Utan ID"})

    def test_create_source(self):
        src = self.Source.create({
            "name": "Testkälla",
            "source_type": "news",
        })
        self.assertTrue(src.id)

    def test_create_witness(self):
        w = self.Witness.create({"name": "Vittne A"})
        self.assertTrue(w.id)

    def test_create_verification(self):
        enc = self.Encounter.create({"encounter_id": "SWE_TEST_0002"})
        v = self.Verification.create({
            "name": "Verifiering 1",
            "encounter_id": enc.id,
            "change_date": "2024-01-01",
        })
        self.assertTrue(v.id)
        self.assertEqual(v.encounter_id.id, enc.id)
