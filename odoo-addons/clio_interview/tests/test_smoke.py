from odoo.tests.common import TransactionCase


class TestSmokeClioInterview(TransactionCase):
    """Smoke test — clio_interview: template och session."""

    def setUp(self):
        super().setUp()
        self.Template = self.env["clio.interview.template"]
        self.Session = self.env["clio.interview.session"]

    def test_models_registered(self):
        self.assertIn("clio.interview.template", self.env)
        self.assertIn("clio.interview.session", self.env)
        self.assertIn("clio.interview.message", self.env)

    def test_create_template(self):
        t = self.Template.create({
            "name": "Testmall",
            "subject": "Testämne",
            "opening_question": "Berätta om dig själv?",
        })
        self.assertTrue(t.id)
        self.assertTrue(t.active)

    def test_template_required_fields(self):
        with self.assertRaises(Exception):
            self.Template.create({"name": "Ofullständig"})

    def test_create_session(self):
        partner = self.env["res.partner"].create({"name": "Testdeltagare"})
        s = self.Session.create({
            "partner_id": partner.id,
            "status": "active",
        })
        self.assertTrue(s.id)
        self.assertEqual(s.status, "active")

    def test_session_participant_email_computed(self):
        partner = self.env["res.partner"].create({
            "name": "Emailtest",
            "email": "deltagare@example.com",
        })
        s = self.Session.create({"partner_id": partner.id})
        self.assertEqual(s.participant_email, "deltagare@example.com")
