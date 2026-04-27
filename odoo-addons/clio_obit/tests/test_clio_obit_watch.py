"""
test_clio_obit_watch.py
Testfall för clio.obit.watch-modellen.

Kör med:
    docker exec odoo-odoo-1 odoo -d aiab --test-enable --stop-after-init \
        -i clio_obit --log-level=test
"""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestClioObitWatch(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user1 = self.env.ref("base.user_admin")
        self.user2 = self.env["res.users"].create({
            "name":  "Testbevakare",
            "login": "testbevakare@arvas.se",
            "email": "testbevakare@arvas.se",
        })
        self.partner = self.env["res.partner"].create({
            "name":       "Test Testsson",
            "is_company": False,
        })

    # ── Grundläggande skapande ────────────────────────────────────────────────

    def test_create_watch(self):
        """En watch-rad ska skapas utan fel."""
        watch = self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user1.id,
            "priority":   "viktig",
        })
        self.assertEqual(watch.priority, "viktig")
        self.assertTrue(watch.id)

    def test_partner_watch_computed(self):
        """clio_obit_watch ska vara True när watch-rad finns."""
        self.assertFalse(self.partner.clio_obit_watch)
        self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user1.id,
        })
        self.partner.invalidate_recordset()
        self.assertTrue(self.partner.clio_obit_watch)

    def test_partner_watch_false_after_delete(self):
        """clio_obit_watch ska bli False när sista watch-raden tas bort."""
        watch = self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user1.id,
        })
        self.partner.invalidate_recordset()
        self.assertTrue(self.partner.clio_obit_watch)
        watch.unlink()
        self.partner.invalidate_recordset()
        self.assertFalse(self.partner.clio_obit_watch)

    # ── Duplikatskydd ─────────────────────────────────────────────────────────

    def test_duplicate_watch_raises(self):
        """Samma användare får inte bevaka samma person två gånger."""
        self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user1.id,
        })
        with self.assertRaises(Exception):
            self.env["clio.obit.watch"].create({
                "partner_id": self.partner.id,
                "user_id":    self.user1.id,
            })

    def test_two_users_same_partner(self):
        """Två olika användare ska kunna bevaka samma person."""
        w1 = self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user1.id,
            "priority":   "viktig",
        })
        w2 = self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user2.id,
            "priority":   "normal",
        })
        self.assertEqual(len(self.partner.watch_ids), 2)
        self.assertNotEqual(w1.priority, w2.priority)

    # ── Effektiv e-post ───────────────────────────────────────────────────────

    def test_effective_email_from_user(self):
        """effective_email ska falla tillbaka på användarens e-post."""
        watch = self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user1.id,
        })
        self.assertEqual(watch.effective_email, self.user1.email or "")

    def test_effective_email_override(self):
        """notify_email ska åsidosätta användarens e-post."""
        watch = self.env["clio.obit.watch"].create({
            "partner_id":   self.partner.id,
            "user_id":      self.user1.id,
            "notify_email": "annan@arvas.se",
        })
        self.assertEqual(watch.effective_email, "annan@arvas.se")

    # ── Cascade-borttagning ───────────────────────────────────────────────────

    def test_watch_deleted_when_partner_deleted(self):
        """Watch-rader ska tas bort när partnern tas bort (cascade)."""
        watch = self.env["clio.obit.watch"].create({
            "partner_id": self.partner.id,
            "user_id":    self.user1.id,
        })
        watch_id = watch.id
        self.partner.unlink()
        self.assertFalse(self.env["clio.obit.watch"].browse(watch_id).exists())
