# -*- coding: utf-8 -*-
"""Sharing a company doc with a link, and downloading it as a PDF."""
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged

from .test_sediba_docs import DocsCase


@tagged('post_install', '-at_install')
class TestSedibaShare(DocsCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ReaderWs = cls.env['sediba.workspace'].with_user(cls.reader)
        cls.doc = cls.Doc.create({'name': 'Proposal', 'summary': 'For one reader', 'body': '<p>First text</p>',
                                  'question_ids': [(0, 0, {'name': 'Is it free?', 'answer': 'Yes.'})]})

    def test_link_is_off_until_a_writer_turns_it_on(self):
        self.assertFalse(self.Ws.ws_doc(self.doc.id)['props']['share'])
        data = self.Ws.ws_doc_set(self.doc.id, {'shared': True})
        link = data['props']['share']
        token = self.doc.share_token
        self.assertEqual(link, '/library/shared/%s' % token)
        self.assertGreaterEqual(len(token), 30)
        # Turning it on again keeps the same link; it is not content, so nothing to publish.
        self.assertEqual(self.Ws.ws_doc_set(self.doc.id, {'shared': True})['props']['share'], link)
        self.assertFalse(data['changes'])
        # Off forgets the key: the old link is gone and a new one is different.
        self.assertFalse(self.Ws.ws_doc_set(self.doc.id, {'shared': False})['props']['share'])
        self.assertFalse(self.env['sediba.workspace']._doc_page_shared(token))
        self.Ws.ws_doc_set(self.doc.id, {'shared': True})
        self.assertNotEqual(self.doc.share_token, token)

    def test_only_a_writer_shares_and_a_reader_never_sees_the_key(self):
        self.doc.action_share()
        with self.assertRaises(AccessError):
            self.ReaderWs.ws_doc_set(self.doc.id, {'shared': False})
        self.assertFalse(self.ReaderWs.ws_doc(self.doc.id)['props'])
        with self.assertRaises(AccessError):
            self.doc.with_user(self.reader).share_token
        self.assertTrue(self.doc.share_token)
        # A copy starts unshared.
        self.assertFalse(self.doc.copy().share_token)

    def test_what_the_link_shows(self):
        Page = self.env['sediba.workspace'].with_user(self.env.ref('base.public_user'))
        self.assertFalse(Page._doc_page_shared(''))
        self.assertFalse(Page._doc_page_shared('short'))
        self.assertFalse(Page._doc_page_shared('x' * 32))
        self.doc.action_share()
        token = self.doc.share_token
        # A draft that was never published: the text as it stands, and no owner's name.
        page = Page._doc_page_shared(token)
        self.assertEqual((page['name'], page['summary'], page['owner']), ('Proposal', 'For one reader', False))
        self.assertIn('First text', page['parts'][0]['html'])
        self.assertEqual(page['questions'], [{'name': 'Is it free?', 'answer': 'Yes.'}])
        # Once published, the link shows the published version, not later edits.
        self.doc.action_publish()
        self.doc.write({'name': 'Proposal 2', 'body': '<p>Second text</p>'})
        page = Page._doc_page_shared(token)
        self.assertEqual(page['name'], 'Proposal')
        self.assertIn('First text', page['parts'][0]['html'])
        self.doc.action_publish()
        self.assertEqual(Page._doc_page_shared(token)['name'], 'Proposal 2')
        # An archived doc is gone from its link.
        self.doc.active = False
        self.assertFalse(Page._doc_page_shared(token))

    def test_the_page_is_whole_and_safe_to_hand_out(self):
        Ws = self.env['sediba.workspace']
        self.doc.write({'name': 'Fish & <chips>', 'flows': {'f1': {'name': 'How it goes', 'steps': [
            {'id': 1, 'kind': 'start', 'text': 'Someone asks', 'detail': '', 'next': [{'label': '', 'to': 2}]},
            {'id': 2, 'kind': 'end', 'text': 'Done', 'detail': '', 'next': []}]}},
            'body': '<p>Before</p><div class="o_sdb_flow o_sdb_flow_f1">x</div><p>After</p>'})
        self.doc.action_share()
        html = str(Ws._doc_page_html(Ws._doc_page_shared(self.doc.share_token), pdf_url='/library/shared/x/pdf'))
        self.assertTrue(html.lstrip().startswith('<!DOCTYPE html>'))
        self.assertIn('Fish &amp; &lt;chips&gt;', html)
        self.assertIn('noindex', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('<link', html)
        for words in ('Before', 'How it goes', 'Someone asks', 'Then step 2.', 'After', 'Is it free?',
                      'Download PDF', 'href="/library/shared/x/pdf"'):
            self.assertIn(words, html)
        # The copy that becomes the PDF carries no link bar.
        self.assertNotIn('Download PDF', str(Ws._doc_page_html(Ws._doc_page_shared(self.doc.share_token), for_pdf=True)))
        self.assertEqual(Ws._doc_file_name({'name': 'Fish & <chips>: 2027/28'}), 'Fish chips 2027 28.pdf')

    def test_pictures_are_written_into_the_page(self):
        png = (b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
        Att = self.env['ir.attachment']
        own = Att.create({'name': 'own.png', 'datas': png, 'res_model': 'sediba.doc', 'res_id': self.doc.id})
        loose = Att.create({'name': 'loose.png', 'datas': png, 'res_model': 'ir.ui.view'})
        other = Att.create({'name': 'other.png', 'datas': png, 'res_model': 'res.partner',
                            'res_id': self.writer.partner_id.id})
        note = Att.create({'name': 'note.txt', 'raw': b'secret words', 'mimetype': 'text/plain',
                           'res_model': 'sediba.doc', 'res_id': self.doc.id})
        self.assertEqual(own.mimetype, 'image/png')
        self.doc.write({'body': (
            '<p>Before</p>'
            '<p><img class="img-fluid" src="/web/image/%s/own.png" alt="Own"></p>'
            '<p><img src="/web/image/%s-abc123def/loose.png"></p>'
            '<p><img src="/web/image/%s/other.png"></p>'
            '<p><img src="/web/image/%s/note.txt"></p>'
            '<p><img src="/web/image/99999999"></p>') % (own.id, loose.id, other.id, note.id)})
        self.doc.action_share()
        Ws = self.env['sediba.workspace']
        for page in (Ws.with_user(self.env.ref('base.public_user'))._doc_page_shared(self.doc.share_token),
                     self.ReaderWs._doc_page_for(self.doc.id)):
            html = str(page['parts'][0]['html'])
            self.assertEqual(html.count('src="data:image/png;base64,'), 2)
            self.assertIn('alt="Own"', html)
            # Another record's file, a file that is no picture, and one that is gone stay as they were.
            self.assertIn('src="/web/image/%s/other.png"' % other.id, html)
            self.assertIn('src="/web/image/%s/note.txt"' % note.id, html)
            self.assertIn('src="/web/image/99999999"', html)
            self.assertNotIn('c2VjcmV0', html)
        # The page a signed-in reader works in is left alone.
        self.assertNotIn('data:image', str(self.Ws.ws_doc(self.doc.id)['parts'][0]['html']))

    def test_signed_in_pdf_follows_what_the_reader_may_see(self):
        self.doc.write({'space_ids': [(6, 0, self.jobs.ids)]})
        # A draft: in the Library yes, from inside an app no.
        self.assertEqual(self.ReaderWs._doc_page_for(self.doc.id)['name'], 'Proposal')
        self.assertFalse(self.ReaderWs._doc_page_for(self.doc.id, 'test_jobs'))
        self.doc.action_publish()
        self.doc.write({'name': 'Proposal 2'})
        self.assertEqual(self.ReaderWs._doc_page_for(self.doc.id, 'test_jobs')['name'], 'Proposal')
        self.assertFalse(self.ReaderWs._doc_page_for(self.doc.id, 'test_calls'))
        self.assertEqual(self.ReaderWs._doc_page_for(self.doc.id)['name'], 'Proposal 2')
        version = self.doc.version_ids[0]
        self.assertEqual(self.ReaderWs._doc_page_for(self.doc.id, False, version.id)['name'], 'Proposal')
        self.assertEqual(self.ReaderWs._doc_page_for(self.doc.id)['owner'], 'Thandi Writer')
        self.assertFalse(self.ReaderWs._doc_page_for(0))
        with self.assertRaises(AccessError):
            self.env['sediba.workspace'].with_user(self.outsider)._doc_page_for(self.doc.id)


@tagged('post_install', '-at_install')
class TestSedibaShareHttp(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = new_test_user(cls.env, 'sediba_share_reader', groups='base.group_user,sediba.group_reader',
                                   password='sediba_share_reader')
        cls.doc = cls.env['sediba.doc'].create({'name': 'Shared plan', 'body': '<p>Plain words</p>'})

    def test_shared_page_needs_no_sign_in(self):
        self.assertEqual(self.url_open('/library/shared/%s' % ('y' * 32)).status_code, 404)
        self.doc.action_share()
        response = self.url_open('/library/shared/%s' % self.doc.share_token)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Plain words', response.text)
        self.assertIn('noindex', response.headers['X-Robots-Tag'])
        self.assertIn("default-src 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        pdf = self.url_open('/library/shared/%s/pdf' % self.doc.share_token)
        self.assertEqual((pdf.status_code, pdf.headers['Content-Type']), (200, 'application/pdf'))
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertIn('Shared%20plan.pdf', pdf.headers['Content-Disposition'])
        self.doc.action_share(False)
        self.assertEqual(self.url_open('/library/shared/%s' % ('y' * 32)).status_code, 404)

    def test_signed_in_pdf(self):
        # Not signed in: sent to the sign-in page, never the file.
        response = self.url_open('/library/doc/%s/pdf' % self.doc.id)
        self.assertNotEqual(response.headers.get('Content-Type'), 'application/pdf')
        self.authenticate('sediba_share_reader', 'sediba_share_reader')
        pdf = self.url_open('/library/doc/%s/pdf' % self.doc.id)
        self.assertEqual((pdf.status_code, pdf.headers['Content-Type']), (200, 'application/pdf'))
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        # From inside an app a draft is not there.
        self.assertEqual(self.url_open('/library/doc/%s/pdf?space=test_jobs' % self.doc.id).status_code, 404)
        self.assertEqual(self.url_open('/library/doc/999999/pdf').status_code, 404)
