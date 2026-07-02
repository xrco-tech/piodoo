# -*- coding: utf-8 -*-
"""Tests for the Odoo → Meta publish path.

These tests mock every network call so the suite stays hermetic — they
verify the payload we ship to Meta rather than the round-trip. Pair them
with occasional live smoke runs against a sandbox WABA when needed.
"""

import json
from unittest.mock import patch, MagicMock

from odoo.tests import common, tagged


def _fake_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(body or {})
    resp.json.return_value = body or {}
    def _raise():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}: {resp.text}")
    resp.raise_for_status = _raise
    return resp


def _build_lead_capture_flow(env):
    """Build a small, realistic flow via the structured API. Returns the
    flow record."""
    Flow   = env['whatsapp.flow']
    Screen = env['whatsapp.flow.screen']
    Comp   = env['whatsapp.flow.component']

    f = Flow.create({'name': 'lead_capture_test', 'category': 'LEAD_GENERATION'})
    welcome = Screen.create({
        'flow_id': f.id, 'screen_id': 'WELCOME', 'title': 'Get in touch',
        'sequence': 10,
    })
    Comp.create({'screen_id': welcome.id, 'component_type': 'TextHeading',
                 'text': 'Get in touch', 'sequence': 10})
    Comp.create({'screen_id': welcome.id, 'component_type': 'TextInput',
                 'name': 'first_name', 'label': 'First name',
                 'required': True, 'sequence': 20})
    thanks = Screen.create({
        'flow_id': f.id, 'screen_id': 'THANKS', 'title': 'Thanks',
        'sequence': 20, 'terminal': True, 'success': True,
    })
    Comp.create({'screen_id': welcome.id, 'component_type': 'Footer',
                 'label': 'Submit', 'sequence': 30,
                 'action_type': 'navigate', 'target_screen_id': thanks.id})
    Comp.create({'screen_id': thanks.id, 'component_type': 'TextBody',
                 'text': "You're all set!", 'sequence': 10})
    Comp.create({'screen_id': thanks.id, 'component_type': 'Footer',
                 'label': 'Done', 'sequence': 20, 'action_type': 'complete'})
    return f


@tagged('whatsapp', 'flow_meta', 'post_install', '-at_install')
class TestMetaCreateFlow(common.TransactionCase):
    """Verify action_create_flow_meta ships the right payload to Meta."""

    def _seed_system_creds(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('comm_whatsapp.access_token', 'TEST_TOKEN')
        icp.set_param('comm_whatsapp.business_account_id', 'WABA_TEST_ID')

    def test_create_flow_posts_payload_with_categories_and_json(self):
        """The POST body must have name, categories, and the generated
        flow definition inline in `json_flow` (Meta's key name)."""
        self._seed_system_creds()
        f = _build_lead_capture_flow(self.env)

        with patch('odoo.addons.comm_whatsapp.models.whatsapp_flow.requests') as mock_requests:
            mock_requests.post.return_value = _fake_response(
                200, {'id': 'FLOW_ID_XYZ', 'success': True})
            f.action_create_flow_meta()

        self.assertEqual(mock_requests.post.call_count, 1)
        call = mock_requests.post.call_args
        # URL scoped to the configured WABA.
        self.assertIn('WABA_TEST_ID/flows', call.args[0])
        headers = call.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer TEST_TOKEN')
        # Payload — Meta's create endpoint expects json_flow (dict).
        body = call.kwargs.get('json') or {}
        self.assertEqual(body.get('name'), 'lead_capture_test')
        self.assertEqual(body.get('categories'), ['LEAD_GENERATION'])
        self.assertIn('json_flow', body)
        parsed = body['json_flow']
        # Accept either an inline dict or a JSON string — Meta accepts
        # both variants; we currently emit a dict.
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        self.assertEqual(parsed['version'], '7.0')
        self.assertEqual(
            sorted(s['id'] for s in parsed['screens']),
            ['THANKS', 'WELCOME'],
        )
        # The response's id becomes our flow_id_meta.
        self.assertEqual(f.flow_id_meta, 'FLOW_ID_XYZ')

    def test_create_flow_uses_per_flow_account_creds(self):
        """When the flow is bound to an account, its credentials win over
        the legacy system parameters."""
        acc = self.env['comm.whatsapp.account'].create({
            'name': 'Test WABA', 'phone_number': '+27600000000',
            'phone_number_id': 'PNID_TEST',
            'business_account_id': 'ACC_WABA_ID',
            'access_token': 'ACC_TOKEN',
        })
        # System params exist too — they must be ignored.
        self._seed_system_creds()
        f = _build_lead_capture_flow(self.env)
        f.account_id = acc.id

        with patch('odoo.addons.comm_whatsapp.models.whatsapp_flow.requests') as mock_requests:
            mock_requests.post.return_value = _fake_response(
                200, {'id': 'FID', 'success': True})
            f.action_create_flow_meta()

        call = mock_requests.post.call_args
        self.assertIn('ACC_WABA_ID/flows', call.args[0])
        self.assertEqual(call.kwargs['headers']['Authorization'],
                         'Bearer ACC_TOKEN')

    def test_create_flow_missing_creds_returns_notification_not_raise(self):
        """No creds anywhere → returns a display_notification with
        `type=danger` instead of raising."""
        f = _build_lead_capture_flow(self.env)
        # Wipe both sources.
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('comm_whatsapp.access_token', '')
        icp.set_param('comm_whatsapp.long_lived_token', '')
        icp.set_param('comm_whatsapp.business_account_id', '')

        with patch('odoo.addons.comm_whatsapp.models.whatsapp_flow.requests') as mock_requests:
            action = f.action_create_flow_meta()
            self.assertEqual(mock_requests.post.call_count, 0)
        self.assertEqual(action.get('tag'), 'display_notification')
        self.assertEqual(action['params']['type'], 'danger')


@tagged('whatsapp', 'flow_meta', 'post_install', '-at_install')
class TestMetaPublishFlow(common.TransactionCase):
    """Verify action_publish_flow's payload + status check."""

    def _seed(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('comm_whatsapp.access_token', 'TEST_TOKEN')
        icp.set_param('comm_whatsapp.business_account_id', 'WABA_TEST_ID')

    def test_publish_status_check_then_publish_post(self):
        """Publish first GETs the current status, then POSTs to the flow's
        Graph URL with json_flow + status=PUBLISHED in one call."""
        self._seed()
        f = _build_lead_capture_flow(self.env)
        f.flow_id_meta = 'FLOW_ABC'

        with patch('odoo.addons.comm_whatsapp.models.whatsapp_flow.requests') as mock_requests:
            mock_requests.get.return_value = _fake_response(
                200, {'id': 'FLOW_ABC', 'status': 'DRAFT'})
            mock_requests.post.return_value = _fake_response(
                200, {'success': True})
            f.action_publish_flow()

        # One GET (status check) + one POST (update+publish).
        self.assertEqual(mock_requests.get.call_count, 1)
        self.assertEqual(mock_requests.post.call_count, 1)
        # Every call carried the bearer token.
        for c in list(mock_requests.post.call_args_list) + \
                 list(mock_requests.get.call_args_list):
            self.assertEqual(c.kwargs['headers']['Authorization'],
                             'Bearer TEST_TOKEN')
        # The POST must hit the flow's Graph URL, carry json_flow +
        # status=PUBLISHED, and target the exact flow_id.
        post_call = mock_requests.post.call_args
        self.assertIn('FLOW_ABC', post_call.args[0])
        body = post_call.kwargs.get('json') or {}
        self.assertEqual(body.get('status'), 'PUBLISHED')
        self.assertIn('json_flow', body)
        # Should reflect our built flow.
        parsed = body['json_flow']
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        self.assertEqual(len(parsed.get('screens', [])), 2)
        # Local status flipped to PUBLISHED.
        self.assertEqual(f.status, 'PUBLISHED')

    def test_publish_uses_account_creds_not_system_params(self):
        """Regression: earlier action_publish_flow read the access token
        straight from ir.config_parameter, so a flow bound to an account
        with a fresh token was still published with the (expired) system
        param token. Ensure the resolver is used so account_id wins."""
        # Legacy system params — they must be ignored when the flow has
        # its own account.
        self._seed()
        acc = self.env['comm.whatsapp.account'].create({
            'name': 'Fresh WABA', 'phone_number': '+27600000001',
            'phone_number_id': 'PNID_FRESH',
            'business_account_id': 'ACC_BIZ',
            'access_token': 'FRESH_TOKEN',
        })
        f = _build_lead_capture_flow(self.env)
        f.account_id = acc.id
        f.flow_id_meta = 'FLOW_FRESH'

        with patch('odoo.addons.comm_whatsapp.models.whatsapp_flow.requests') as mock_requests:
            mock_requests.get.return_value = _fake_response(
                200, {'id': 'FLOW_FRESH', 'status': 'DRAFT'})
            mock_requests.post.return_value = _fake_response(
                200, {'success': True})
            f.action_publish_flow()

        # Every request must carry the account's fresh token, NOT
        # TEST_TOKEN from the system params.
        for c in list(mock_requests.get.call_args_list) + \
                 list(mock_requests.post.call_args_list):
            self.assertEqual(
                c.kwargs['headers']['Authorization'],
                'Bearer FRESH_TOKEN',
                "publish used the wrong token — the resolver was bypassed",
            )

    def test_publish_update_on_already_published_flow(self):
        """Meta accepts JSON updates on already-published flows (they
        create a new preview version). Our publish action must send
        json_flow without status=PUBLISHED, so Meta doesn't reject the
        redundant status transition, and must NOT clobber the local
        status field."""
        self._seed()
        f = _build_lead_capture_flow(self.env)
        f.flow_id_meta = 'FLOW_PUB'
        f.status = 'PUBLISHED'  # already published locally too

        with patch('odoo.addons.comm_whatsapp.models.whatsapp_flow.requests') as mock_requests:
            mock_requests.get.return_value = _fake_response(
                200, {'id': 'FLOW_PUB', 'status': 'PUBLISHED'})
            mock_requests.post.return_value = _fake_response(
                200, {'success': True})
            action = f.action_publish_flow()

        # POST must have fired (update path); status key must be absent.
        self.assertEqual(mock_requests.post.call_count, 1)
        body = mock_requests.post.call_args.kwargs.get('json') or {}
        self.assertIn('json_flow', body)
        self.assertNotIn('status', body,
            "update path must not send status=PUBLISHED (already published)")
        # Success surfaces as a non-sticky "Update pushed" notification.
        self.assertEqual(action['params']['type'], 'success')
        # Local status stays as it was.
        self.assertEqual(f.status, 'PUBLISHED')

    def test_publish_refuses_deprecated(self):
        """DEPRECATED / BLOCKED / THROTTLED are still refused with a
        danger notification and never POSTed."""
        self._seed()
        f = _build_lead_capture_flow(self.env)
        f.flow_id_meta = 'FLOW_DEP'

        with patch('odoo.addons.comm_whatsapp.models.whatsapp_flow.requests') as mock_requests:
            mock_requests.get.return_value = _fake_response(
                200, {'id': 'FLOW_DEP', 'status': 'DEPRECATED'})
            action = f.action_publish_flow()
            self.assertEqual(mock_requests.post.call_count, 0)
        self.assertEqual(action['params']['type'], 'danger')


@tagged('whatsapp', 'flow_meta', 'flow_builder',
        'post_install', '-at_install')
class TestGeneratorAgainstMetaSchema(common.TransactionCase):
    """Static shape checks against the Meta v7 schema — sanity guards
    against regressions in the generator that would otherwise only
    surface at publish time."""

    def test_all_component_types_generate_a_type_string(self):
        """Every component_type we advertise must serialise to a Meta
        JSON node with a matching `type`."""
        Component = self.env['whatsapp.flow.component']
        flow = self.env['whatsapp.flow'].create({'name': 'shape_test'})
        screen = self.env['whatsapp.flow.screen'].create({
            'flow_id': flow.id, 'screen_id': 'S', 'title': 'S',
            'terminal': True,
        })
        # For each Selection value, generate a minimum-viable component
        # and confirm _render_flow_json returns a dict whose `type`
        # matches the Selection key.
        types = [v[0] for v in Component._fields['component_type'].selection]
        for t in types:
            vals = {'screen_id': screen.id, 'component_type': t}
            if t in ('TextInput', 'TextArea'):
                vals.update(name='x', label='X')
            elif t in ('Dropdown', 'RadioButtonsGroup', 'CheckboxGroup',
                       'ChipsSelector'):
                vals.update(name='x', label='X')
            elif t in ('DatePicker', 'CalendarPicker'):
                vals.update(name='d', label='D')
            elif t == 'Footer':
                vals.update(label='Submit', action_type='complete')
            elif t == 'EmbeddedLink':
                vals.update(label='More', action_type='open_url',
                            open_url='https://example.com/help')
            elif t == 'OptIn':
                vals.update(name='ok', label='I agree', action_type='complete')
            elif t in ('TextHeading', 'TextSubheading', 'TextBody',
                       'TextCaption', 'RichText'):
                vals['text'] = 'hi'
            elif t == 'Image':
                vals['image_src'] = 'https://example.com/x.png'
            elif t == 'ImageCarousel':
                vals['images_ref'] = '${data.gallery}'
            elif t == 'NavigationList':
                vals.update(name='nav', label='Pick one')
            elif t in ('PhotoPicker', 'DocumentPicker'):
                vals.update(name='files', label='Upload')
            comp = Component.create(vals)
            node = comp._render_flow_json()
            self.assertIsNotNone(node, f"{t}: renderer returned None")
            self.assertEqual(node.get('type'), t,
                             f"{t}: node.type = {node.get('type')!r}")

    def test_generated_json_is_string_parseable(self):
        """The final flow_json field must always be a JSON string, not
        a dict — Meta's endpoint requires a string."""
        f = _build_lead_capture_flow(self.env)
        f.invalidate_recordset(['flow_json'])
        self.assertIsInstance(f.flow_json, str)
        parsed = json.loads(f.flow_json)
        self.assertIn('version', parsed)
        self.assertIn('screens', parsed)
