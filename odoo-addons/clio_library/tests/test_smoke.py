from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSmokeClioLibrary(TransactionCase):
    """Smoke test — clio_library: library.book och library.rating."""

    def setUp(self):
        super().setUp()
        self.Book = self.env["library.book"]
        self.Rating = self.env["library.rating"]

    def test_models_registered(self):
        self.assertIn("library.book", self.env)
        self.assertIn("library.rating", self.env)

    def test_create_book(self):
        book = self.Book.create({"name": "Testbok"})
        self.assertTrue(book.id)
        self.assertEqual(book.name, "Testbok")

    def test_book_name_required(self):
        with self.assertRaises(Exception):
            self.Book.create({})

    def test_create_rating(self):
        book = self.Book.create({"name": "Betygsbok"})
        rating = self.Rating.create({
            "book_id": book.id,
            "user_id": self.env.user.id,
            "rating": 4,
        })
        self.assertTrue(rating.id)
        self.assertEqual(rating.book_id.name, "Betygsbok")

    def test_rating_cascade_delete(self):
        book = self.Book.create({"name": "Kaskadbok"})
        rating = self.Rating.create({
            "book_id": book.id,
            "user_id": self.env.user.id,
        })
        book_id = book.id
        book.unlink()
        self.assertFalse(self.Rating.search([("book_id", "=", book_id)]))
