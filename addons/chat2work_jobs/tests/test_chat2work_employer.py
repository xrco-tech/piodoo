# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from ..models.chat2work_employer import loose_key, name_key


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workEmployer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = cls.env['chat2work.listing.source'].create({'name': 'Zze site'})
        cls.Employer = cls.env['chat2work.employer']

    def _job(self, employer, title='Cashier', **vals):
        return self.env['chat2work.listing'].create(dict(
            {'title': title, 'source_id': self.source.id, 'employer': employer}, **vals))

    def test_keys(self):
        self.assertEqual(name_key('Zze  Retail (Pty) Ltd.'), name_key('zze retail'))
        self.assertNotEqual(name_key('Zze Retail Group'), name_key('Zze Retail'))
        self.assertEqual(loose_key('Zze Retail Group'), loose_key('The Zze Retail Holdings'))

    def test_listing_gets_its_employer(self):
        first = self._job('Zze Retail (Pty) Ltd')
        second = self._job('zze retail', title='Packer')
        third = self._job('Zze Logistics')
        self.assertTrue(first.employer_id)
        self.assertEqual(first.employer_id, second.employer_id, 'company-form words do not make a new employer')
        self.assertNotEqual(first.employer_id, third.employer_id)
        self.assertEqual(first.employer_id.state, 'new')
        self.assertEqual(first.employer_state, 'new')
        self.assertEqual(first.employer_id.listing_count, 2)
        self.assertFalse(self._job(False).employer_id, 'no name, no employer')
        # Renaming the employer on a listing moves it.
        second.employer = 'Zze Logistics'
        self.assertEqual(second.employer_id, third.employer_id)
        # A new employer never stops a job from being verified.
        first.action_mark_verified()
        self.assertEqual(first.verification_state, 'verified')

    def test_answer_join_and_not_same(self):
        main = self._job('Zze Retail Group').employer_id
        other = self._job('Zze Retail Grp', title='Packer').employer_id
        unrelated = self._job('Zze Mining').employer_id
        self.assertIn(other, main._similar())
        self.assertNotIn(unrelated, main._similar())

        main.action_set_state('verified')
        self.assertEqual((main.state, main.checked_by_id), ('verified', self.env.user))

        main.action_join(other)
        self.assertFalse(other.exists())
        self.assertEqual(main.listing_count, 2)
        self.assertIn('Zze Retail Grp', main.alias_ids.mapped('name'))
        # A later job under the old spelling lands on the joined employer.
        self.assertEqual(self._job('ZZE RETAIL GRP', title='Driver').employer_id, main)

        lookalike = self._job('Zze Retail Group Holdings').employer_id
        self.assertIn(lookalike, main._similar())
        main.action_not_same(lookalike)
        self.assertNotIn(lookalike, main._similar())
        self.assertNotIn(main, lookalike._similar())

    def test_backfill(self):
        job = self._job('Zze Old Employer')
        job.employer_id = False
        self.env['chat2work.listing']._c2w_link_all_employers()
        self.assertEqual(job.employer_id.name, 'Zze Old Employer')

    def test_form_buttons(self):
        """The record form's buttons record who answered, like the workspace."""
        employer = self.env['chat2work.employer'].create({'name': 'Form Button Traders'})
        employer.action_mark_verified()
        self.assertEqual(employer.state, 'verified')
        self.assertEqual(employer.checked_by_id, self.env.user)
        self.assertTrue(employer.checked_at)
        employer.action_mark_invalid()
        self.assertEqual(employer.state, 'invalid')
        employer.action_mark_unsure()
        self.assertEqual(employer.state, 'unsure')
        employer.action_mark_new()
        self.assertEqual(employer.state, 'new')
        action = employer.action_open_listings()
        self.assertEqual(action['res_model'], 'chat2work.listing')
        self.assertEqual(action['domain'], [('employer_id', '=', employer.id)])

    def test_contact_record(self):
        """The contact is made on first use, then the same one is opened."""
        employer = self.env['chat2work.employer'].create({'name': 'Contact Link Traders', 'registration_no': '2019/1/07'})
        self.assertFalse(employer.partner_id)
        action = employer.action_open_partner()
        partner = employer.partner_id
        self.assertTrue(partner.is_company)
        self.assertEqual(partner.name, 'Contact Link Traders')
        self.assertEqual(action['res_id'], partner.id)
        self.assertEqual(employer.action_open_partner()['res_id'], partner.id)
        # Joining another spelling keeps a contact the other one had.
        other = self.env['chat2work.employer'].create({'name': 'Zzq Joined Works'})
        keeper = self.env['chat2work.employer'].create({'name': 'Zzq Joined Works Group'})
        other.action_open_partner()
        kept = other.partner_id
        keeper.action_join(other)
        self.assertEqual(keeper.partner_id, kept)
