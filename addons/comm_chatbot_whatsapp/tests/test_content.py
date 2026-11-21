# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.comm_chatbot_whatsapp.models.adapter import build_content, _framed


@tagged('post_install', '-at_install')
class TestWhatsappContent(BaseCase):
    """What is handed to WhatsApp for a rendered step. Nothing is sent."""

    def _options(self, *labels):
        return [{'label': label, 'value': label.lower()} for label in labels]

    def test_plain_text(self):
        payload = {'header': 'Hello', 'body': 'How are you?', 'footer': 'Reply STOP'}
        self.assertIsNone(build_content(payload))
        self.assertEqual(_framed(payload), '*Hello*\n\nHow are you?\n\n_Reply STOP_')
        self.assertEqual(_framed({'body': 'Just this'}), 'Just this')

    def test_buttons_with_header_and_footer(self):
        content = build_content({
            'header': 'Welcome', 'body': 'What do you need?', 'footer': 'Reply STOP',
            'options': self._options('Find a job', 'A very long label that is cut off'),
        })
        inter = content['interactive']
        self.assertEqual((content['type'], inter['type']), ('interactive', 'button'))
        self.assertEqual(inter['header'], {'type': 'text', 'text': 'Welcome'})
        self.assertEqual(inter['body'], {'text': 'What do you need?'})
        self.assertEqual(inter['footer'], {'text': 'Reply STOP'})
        buttons = inter['action']['buttons']
        self.assertEqual(buttons[0]['reply'], {'id': 'find a job', 'title': 'Find a job'})
        self.assertEqual(buttons[1]['reply']['title'], 'A very long label th')

    def test_image_takes_the_header(self):
        content = build_content({
            'header': 'Welcome', 'body': 'Pick one',
            'media': [{'kind': 'image', 'url': 'https://example.com/a.png'}],
            'options': self._options('Yes', 'No'),
        })
        self.assertEqual(content['interactive']['header'],
                         {'type': 'image', 'image': {'link': 'https://example.com/a.png'}})

    def test_more_than_three_choices_is_a_list(self):
        content = build_content({
            'body': 'Pick one', 'options': self._options('A', 'B', 'C', 'D')})
        inter = content['interactive']
        self.assertEqual(inter['type'], 'list')
        self.assertEqual([r['title'] for r in inter['action']['sections'][0]['rows']],
                         ['A', 'B', 'C', 'D'])
        self.assertNotIn('header', inter)

    def test_image_without_choices_is_an_image_message(self):
        content = build_content({
            'header': 'Look', 'body': 'Our office',
            'media': [{'kind': 'image', 'url': 'https://example.com/a.png'}]})
        self.assertEqual(content, {'type': 'image', 'image': {
            'link': 'https://example.com/a.png', 'caption': '*Look*\n\nOur office'}})

    def test_numbered_choices_stay_text(self):
        """Choices the renderer already wrote into the body are not buttons."""
        self.assertIsNone(build_content({
            'body': 'Pick\n\n1. A\n2. B',
            'options': [{'label': 'A', 'value': 'a', 'numeric_key': '1'},
                        {'label': 'B', 'value': 'b', 'numeric_key': '2'}]}))
