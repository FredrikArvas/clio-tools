from odoo.tests import TransactionCase
from odoo.exceptions import ValidationError
from psycopg2 import IntegrityError
from odoo.tools import mute_logger


class TestRecoRating(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env

        # Verkstyper (från clio_media seed-data)
        cls.type_book = env.ref('clio_media.work_type_book')
        cls.type_song = env.ref('clio_media.work_type_song')
        cls.type_psalm = env.ref('clio_media.work_type_psalm')
        cls.type_film = env.ref('clio_media.work_type_film')

        # Grupper
        cls.group_curator = env.ref('clio_reco.group_clio_reco_curator')
        cls.group_manager = env.ref('clio_reco.group_clio_reco_manager')

        # Testanvändare
        cls.user_curator = env['res.users'].create({
            'name': 'Kurator Test',
            'login': 'curator_test@test.local',
            'groups_id': [(6, 0, [cls.group_curator.id])],
        })
        cls.user_curator2 = env['res.users'].create({
            'name': 'Kurator2 Test',
            'login': 'curator2_test@test.local',
            'groups_id': [(6, 0, [cls.group_curator.id])],
        })
        cls.user_portal = env['res.users'].create({
            'name': 'Portal Test',
            'login': 'portal_test@test.local',
            'groups_id': [(6, 0, [env.ref('base.group_portal').id])],
        })

        # Verk
        cls.work_book = env['clio.media.work'].create({
            'name': 'Testbok',
            'work_type_id': cls.type_book.id,
        })
        cls.work_film = env['clio.media.work'].create({
            'name': 'Testfilm',
            'work_type_id': cls.type_film.id,
        })

        # Godkänt sammanhang (bok + psalm, icke-känsligt)
        cls.ctx_approved = env['clio.reco.context'].create({
            'name': 'Allmänt betyg',
            'scale_min': 1,
            'scale_max': 5,
            'is_sensitive': False,
            'state': 'approved',
            'work_type_ids': [(6, 0, [cls.type_book.id, cls.type_psalm.id])],
        })

        # Nominerat sammanhang (ska nekas)
        cls.ctx_nominated = env['clio.reco.context'].create({
            'name': 'Nominerat sammanhang',
            'scale_min': 1,
            'scale_max': 5,
            'state': 'nominated',
        })

        # Känsligt godkänt sammanhang
        cls.ctx_sensitive = env['clio.reco.context'].create({
            'name': 'Känsligt sammanhang',
            'scale_min': 1,
            'scale_max': 5,
            'is_sensitive': True,
            'state': 'approved',
        })

        # Sammanhang med betygsättargrupp
        cls.ctx_restricted = env['clio.reco.context'].create({
            'name': 'Begränsat sammanhang',
            'scale_min': 1,
            'scale_max': 5,
            'state': 'approved',
            'rater_group_ids': [(6, 0, [cls.group_manager.id])],
        })

    def test_create_rating_ok(self):
        rating = self.env['clio.reco.rating'].with_user(self.user_curator).create({
            'work_id': self.work_book.id,
            'context_id': self.ctx_approved.id,
            'score': 4,
        })
        self.assertEqual(rating.score, 4)

    def test_score_below_scale_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['clio.reco.rating'].with_user(self.user_curator).create({
                'work_id': self.work_book.id,
                'context_id': self.ctx_approved.id,
                'score': 0,
            })

    def test_score_above_scale_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['clio.reco.rating'].with_user(self.user_curator).create({
                'work_id': self.work_book.id,
                'context_id': self.ctx_approved.id,
                'score': 6,
            })

    def test_nominated_context_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['clio.reco.rating'].with_user(self.user_curator).create({
                'work_id': self.work_book.id,
                'context_id': self.ctx_nominated.id,
                'score': 3,
            })

    def test_wrong_work_type_rejected(self):
        # ctx_approved tillåter bara book och psalm — film ska nekas
        with self.assertRaises(ValidationError):
            self.env['clio.reco.rating'].with_user(self.user_curator).create({
                'work_id': self.work_film.id,
                'context_id': self.ctx_approved.id,
                'score': 3,
            })

    def test_user_outside_rater_group_rejected(self):
        # ctx_restricted kräver manager-grupp
        with self.assertRaises(ValidationError):
            self.env['clio.reco.rating'].with_user(self.user_curator).create({
                'work_id': self.work_book.id,
                'context_id': self.ctx_restricted.id,
                'score': 3,
            })

    def test_manager_bypasses_rater_group(self):
        user_manager = self.env['res.users'].create({
            'name': 'Manager Test',
            'login': 'manager_test@test.local',
            'groups_id': [(6, 0, [self.group_manager.id])],
        })
        rating = self.env['clio.reco.rating'].with_user(user_manager).create({
            'work_id': self.work_book.id,
            'context_id': self.ctx_restricted.id,
            'score': 3,
        })
        self.assertTrue(rating.id)

    @mute_logger('odoo.sql_db')
    def test_unique_constraint(self):
        self.env['clio.reco.rating'].with_user(self.user_curator).create({
            'work_id': self.work_book.id,
            'context_id': self.ctx_approved.id,
            'score': 3,
        })
        with self.assertRaises(IntegrityError):
            self.env['clio.reco.rating'].with_user(self.user_curator).create({
                'work_id': self.work_book.id,
                'context_id': self.ctx_approved.id,
                'score': 5,
            })

    def test_write_score_updates_date(self):
        import datetime
        rating = self.env['clio.reco.rating'].sudo().create({
            'work_id': self.work_book.id,
            'context_id': self.ctx_approved.id,
            'user_id': self.user_curator.id,
            'score': 2,
            'date': datetime.datetime(2020, 1, 1),
        })
        rating.write({'score': 4})
        self.assertGreater(rating.date, datetime.datetime(2020, 1, 2))

    # --- Statistikvy ---

    def _create_rating(self, user, work, ctx, score, consent='unset'):
        return self.env['clio.reco.rating'].sudo().create({
            'work_id': work.id,
            'context_id': ctx.id,
            'user_id': user.id,
            'score': score,
            'consent': consent,
        })

    def test_stat_non_sensitive_counts_unset_and_given(self):
        self._create_rating(self.user_curator, self.work_book, self.ctx_approved, 4, 'unset')
        self._create_rating(self.user_curator2, self.work_book, self.ctx_approved, 2, 'given')
        stat = self.env['clio.reco.rating.stat'].sudo().search([
            ('work_id', '=', self.work_book.id),
            ('context_id', '=', self.ctx_approved.id),
        ])
        self.assertEqual(stat.rating_count, 2)

    def test_stat_non_sensitive_excludes_withdrawn(self):
        self._create_rating(self.user_curator, self.work_book, self.ctx_approved, 5, 'withdrawn')
        stat = self.env['clio.reco.rating.stat'].sudo().search([
            ('work_id', '=', self.work_book.id),
            ('context_id', '=', self.ctx_approved.id),
        ])
        self.assertFalse(stat)

    def test_stat_sensitive_counts_only_given(self):
        work2 = self.env['clio.media.work'].create({
            'name': 'Sensitiv testbok',
            'work_type_id': self.type_book.id,
        })
        self._create_rating(self.user_curator, work2, self.ctx_sensitive, 3, 'unset')
        self._create_rating(self.user_curator2, work2, self.ctx_sensitive, 5, 'given')
        stat = self.env['clio.reco.rating.stat'].sudo().search([
            ('work_id', '=', work2.id),
            ('context_id', '=', self.ctx_sensitive.id),
        ])
        self.assertEqual(stat.rating_count, 1)

    # --- Record rules ---

    def test_curator_cannot_read_others_private_rating(self):
        self.env['clio.reco.rating'].sudo().create({
            'work_id': self.work_book.id,
            'context_id': self.ctx_approved.id,
            'user_id': self.user_curator2.id,
            'score': 3,
            'visibility': 'private',
        })
        ratings = self.env['clio.reco.rating'].with_user(self.user_curator).search([
            ('work_id', '=', self.work_book.id),
            ('user_id', '=', self.user_curator2.id),
        ])
        self.assertFalse(ratings)

    def test_curator_can_read_others_public_rating(self):
        self.env['clio.reco.rating'].sudo().create({
            'work_id': self.work_book.id,
            'context_id': self.ctx_approved.id,
            'user_id': self.user_curator2.id,
            'score': 3,
            'visibility': 'public',
        })
        ratings = self.env['clio.reco.rating'].with_user(self.user_curator).search([
            ('work_id', '=', self.work_book.id),
            ('user_id', '=', self.user_curator2.id),
        ])
        self.assertTrue(ratings)

    def test_portal_user_sees_only_own_ratings(self):
        self.env['clio.reco.rating'].sudo().create({
            'work_id': self.work_book.id,
            'context_id': self.ctx_approved.id,
            'user_id': self.user_curator.id,
            'score': 4,
            'visibility': 'public',
        })
        ratings = self.env['clio.reco.rating'].with_user(self.user_portal).search([
            ('work_id', '=', self.work_book.id),
        ])
        self.assertFalse(ratings)
