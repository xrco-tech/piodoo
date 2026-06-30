# -*- coding: utf-8 -*-
"""Tests for the structured WhatsApp Flow builder."""

import json

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged


@tagged('whatsapp', 'flow_builder', 'post_install', '-at_install')
class TestFlowGenerator(common.TransactionCase):

    def test_empty_flow_generates_minimal_json(self):
        f = self.env['whatsapp.flow'].create({'name': 'empty_flow'})
        out = json.loads(f.flow_json)
        self.assertEqual(out['version'], '7.0')
        self.assertEqual(out['screens'], [])

    def test_lead_capture_flow_generates_expected_shape(self):
        """Build a 2-screen lead capture flow and assert the JSON output
        matches the canonical Meta shape."""
        Flow = self.env['whatsapp.flow']
        Screen = self.env['whatsapp.flow.screen']
        Component = self.env['whatsapp.flow.component']

        flow = Flow.create({'name': 'lead_capture', 'flow_version': '7.0'})

        welcome = Screen.create({
            'flow_id': flow.id, 'screen_id': 'WELCOME',
            'title': 'Welcome', 'sequence': 10,
        })
        Component.create({
            'screen_id': welcome.id, 'component_type': 'TextHeading',
            'text': 'Hi there 👋', 'sequence': 10,
        })
        Component.create({
            'screen_id': welcome.id, 'component_type': 'TextInput',
            'name': 'first_name', 'label': 'First name',
            'required': True, 'sequence': 20,
        })
        thanks = Screen.create({
            'flow_id': flow.id, 'screen_id': 'THANKS',
            'title': 'Thanks', 'sequence': 20, 'terminal': True,
        })
        # Footer on WELCOME → navigates to THANKS
        Component.create({
            'screen_id': welcome.id, 'component_type': 'Footer',
            'label': 'Continue', 'sequence': 30,
            'action_type': 'navigate', 'target_screen_id': thanks.id,
        })
        # Footer on THANKS → complete
        Component.create({
            'screen_id': thanks.id, 'component_type': 'TextBody',
            'text': 'You\'re all set!', 'sequence': 10,
        })
        Component.create({
            'screen_id': thanks.id, 'component_type': 'Footer',
            'label': 'Finish', 'sequence': 20,
            'action_type': 'complete',
        })

        # Re-read so the computed flow_json fires.
        flow.invalidate_recordset(['flow_json'])
        out = json.loads(flow.flow_json)
        self.assertEqual(out['version'], '7.0')
        self.assertEqual(len(out['screens']), 2)
        # routing_model is included since we have a navigate action
        self.assertIn('routing_model', out)
        self.assertEqual(out['routing_model']['WELCOME'], ['THANKS'])
        self.assertEqual(out['routing_model']['THANKS'], [])
        # Terminal flag survives
        thanks_node = next(s for s in out['screens'] if s['id'] == 'THANKS')
        self.assertTrue(thanks_node.get('terminal'))
        # Footer's on-click-action payload forwards every input field
        welcome_node = next(s for s in out['screens'] if s['id'] == 'WELCOME')
        footer = next(c for c in welcome_node['layout']['children']
                      if c['type'] == 'Footer')
        self.assertEqual(footer['on-click-action']['name'], 'navigate')
        self.assertEqual(footer['on-click-action']['next']['name'], 'THANKS')
        self.assertEqual(footer['on-click-action']['payload'],
                         {'first_name': '${form.first_name}'})

    def test_dropdown_renders_options_as_data_source(self):
        Flow = self.env['whatsapp.flow']
        Screen = self.env['whatsapp.flow.screen']
        Component = self.env['whatsapp.flow.component']
        Option = self.env['whatsapp.flow.component.option']

        flow = Flow.create({'name': 'sizing_flow'})
        s = Screen.create({
            'flow_id': flow.id, 'screen_id': 'PICK', 'title': 'Pick size',
            'terminal': True,
        })
        c = Component.create({
            'screen_id': s.id, 'component_type': 'Dropdown',
            'name': 'size', 'label': 'Pick a size',
        })
        Option.create({'component_id': c.id, 'option_id': 'small',  'title': 'Small'})
        Option.create({'component_id': c.id, 'option_id': 'medium', 'title': 'Medium'})

        flow.invalidate_recordset(['flow_json'])
        node = next(c for c in json.loads(flow.flow_json)['screens'][0]['layout']['children']
                    if c['type'] == 'Dropdown')
        self.assertEqual(node['name'], 'size')
        self.assertEqual(len(node['data-source']), 2)
        self.assertEqual(node['data-source'][0]['id'], 'small')


@tagged('whatsapp', 'flow_builder', 'post_install', '-at_install')
class TestFlowValidator(common.TransactionCase):

    def test_flow_without_screens_is_an_error(self):
        f = self.env['whatsapp.flow'].create({'name': 'empty'})
        self.assertEqual(f.validation_status, 'error')
        self.assertIn('at least one screen', f.validation_issues)

    def test_flow_without_terminal_screen_is_an_error(self):
        f = self.env['whatsapp.flow'].create({'name': 'no_term'})
        self.env['whatsapp.flow.screen'].create({
            'flow_id': f.id, 'screen_id': 'ONE', 'title': 'One',
        })
        f.invalidate_recordset(['validation_status', 'validation_issues'])
        self.assertEqual(f.validation_status, 'error')
        self.assertIn('Terminal', f.validation_issues)

    def test_navigate_to_unknown_screen_is_an_error(self):
        f = self.env['whatsapp.flow'].create({'name': 'bad_nav'})
        s1 = self.env['whatsapp.flow.screen'].create({
            'flow_id': f.id, 'screen_id': 'ONE', 'title': 'One',
            'terminal': True,
        })
        s2 = self.env['whatsapp.flow.screen'].create({
            'flow_id': f.id, 'screen_id': 'TWO', 'title': 'Two',
        })
        # Point a footer at TWO, then delete TWO.
        self.env['whatsapp.flow.component'].create({
            'screen_id': s1.id, 'component_type': 'Footer',
            'label': 'Go', 'action_type': 'navigate',
            'target_screen_id': s2.id,
        })
        s2.unlink()
        f.invalidate_recordset(['validation_status', 'validation_issues'])
        # After unlink the FK is null → "missing target" error fires
        self.assertEqual(f.validation_status, 'error')
        self.assertIn('missing a target', f.validation_issues)

    def test_duplicate_input_names_on_same_screen_is_an_error(self):
        f = self.env['whatsapp.flow'].create({'name': 'dup_inputs'})
        s = self.env['whatsapp.flow.screen'].create({
            'flow_id': f.id, 'screen_id': 'FORM', 'title': 'Form', 'terminal': True,
        })
        self.env['whatsapp.flow.component'].create({
            'screen_id': s.id, 'component_type': 'TextInput',
            'name': 'email', 'label': 'A',
        })
        self.env['whatsapp.flow.component'].create({
            'screen_id': s.id, 'component_type': 'TextInput',
            'name': 'email', 'label': 'B',
        })
        f.invalidate_recordset(['validation_status', 'validation_issues'])
        self.assertEqual(f.validation_status, 'error')
        self.assertIn("share the name 'email'", f.validation_issues)

    def test_choice_without_options_is_an_error(self):
        f = self.env['whatsapp.flow'].create({'name': 'no_opts'})
        s = self.env['whatsapp.flow.screen'].create({
            'flow_id': f.id, 'screen_id': 'P', 'title': 'P', 'terminal': True,
        })
        self.env['whatsapp.flow.component'].create({
            'screen_id': s.id, 'component_type': 'Dropdown',
            'name': 'pick', 'label': 'Pick one',
        })
        f.invalidate_recordset(['validation_status', 'validation_issues'])
        self.assertEqual(f.validation_status, 'error')
        self.assertIn('at least one option', f.validation_issues)

    def test_raw_json_mode_accepts_bare_json(self):
        f = self.env['whatsapp.flow'].create({
            'name': 'raw',
            'use_raw_json': True,
            'flow_json': '{"version":"7.0","screens":[]}',
        })
        # In raw mode the generator doesn't fire.
        self.assertEqual(json.loads(f.flow_json)['screens'], [])
        self.assertEqual(f.validation_status, 'ok')

    def test_raw_json_mode_flags_parse_errors(self):
        f = self.env['whatsapp.flow'].create({
            'name': 'bad_raw',
            'use_raw_json': True,
            'flow_json': '{this is not json',
        })
        self.assertEqual(f.validation_status, 'error')
        self.assertIn('parse error', f.validation_issues)


@tagged('whatsapp', 'flow_builder', 'post_install', '-at_install')
class TestFlowJsonImporter(common.TransactionCase):
    """Reverse of the generator: flow_json → structured records."""

    def test_roundtrip_lead_capture(self):
        """Build a flow from the Lead Capture template, dump its JSON, drop
        the structured records, and re-import. The result should produce
        the same JSON shape."""
        Flow = self.env['whatsapp.flow']
        f = Flow.create({'name': 'roundtrip_lc'})
        f.action_template_lead_capture()
        f.invalidate_recordset(['flow_json'])
        original_json = json.loads(f.flow_json)

        # Run the importer in place. It wipes screen_ids and rebuilds them.
        result = f._import_from_flow_json(replace_existing=True)
        self.assertEqual(result['created_screens'], 2)
        self.assertGreater(result['created_components'], 0)
        self.assertEqual(result['warnings'], [])

        # Re-read flow_json and check key structural properties match.
        f.invalidate_recordset(['flow_json'])
        rebuilt = json.loads(f.flow_json)
        self.assertEqual(
            sorted(s['id'] for s in rebuilt['screens']),
            sorted(s['id'] for s in original_json['screens']),
        )
        # Routing model preserved (both screens linked the same way).
        self.assertEqual(rebuilt.get('routing_model'),
                         original_json.get('routing_model'))
        # Same component count per screen.
        for orig, new in zip(original_json['screens'], rebuilt['screens']):
            self.assertEqual(
                len(orig['layout']['children']),
                len(new['layout']['children']),
                f"Component count mismatch on {orig['id']}",
            )

    def test_import_external_json(self):
        """Drop a hand-rolled JSON into an empty flow and import it."""
        Flow = self.env['whatsapp.flow']
        f = Flow.create({
            'name': 'imported_flow',
            'use_raw_json': True,
            'flow_json': json.dumps({
                'version': '7.0',
                'screens': [
                    {
                        'id': 'ASK', 'title': 'Ask',
                        'layout': {
                            'type': 'SingleColumnLayout',
                            'children': [
                                {'type': 'TextHeading', 'text': 'Hi'},
                                {'type': 'TextInput', 'name': 'q',
                                 'label': 'Your question', 'required': True},
                                {'type': 'Footer', 'label': 'Send',
                                 'on-click-action': {
                                     'name': 'navigate',
                                     'next': {'name': 'DONE', 'type': 'screen'},
                                     'payload': {},
                                 }},
                            ],
                        },
                    },
                    {
                        'id': 'DONE', 'title': 'Done', 'terminal': True,
                        'layout': {'type': 'SingleColumnLayout', 'children': [
                            {'type': 'TextBody', 'text': 'Thanks!'},
                            {'type': 'Footer', 'label': 'OK',
                             'on-click-action': {'name': 'complete', 'payload': {}}},
                        ]},
                    },
                ],
            }),
        })

        result = f._import_from_flow_json(replace_existing=True)
        self.assertEqual(result['created_screens'], 2)
        self.assertEqual(result['created_components'], 5)
        self.assertEqual(result['warnings'], [])
        # Navigate target resolved correctly across the two screens.
        ask = self.env['whatsapp.flow.screen'].search([
            ('flow_id', '=', f.id), ('screen_id', '=', 'ASK')], limit=1)
        footer = ask.component_ids.filtered(lambda c: c.component_type == 'Footer')
        self.assertEqual(footer.action_type, 'navigate')
        self.assertEqual(footer.target_screen_id.screen_id, 'DONE')

    def test_import_warns_on_unknown_component(self):
        f = self.env['whatsapp.flow'].create({
            'name': 'with_unknown',
            'use_raw_json': True,
            'flow_json': json.dumps({
                'version': '7.0',
                'screens': [{
                    'id': 'X', 'title': 'X', 'terminal': True,
                    'layout': {'type': 'SingleColumnLayout', 'children': [
                        {'type': 'Calendar', 'name': 'whatever'},
                        {'type': 'TextBody', 'text': 'hi'},
                    ]},
                }],
            }),
        })
        result = f._import_from_flow_json(replace_existing=True)
        self.assertEqual(result['created_components'], 1)
        self.assertTrue(any('Calendar' in w for w in result['warnings']))


@tagged('whatsapp', 'flow_builder', 'post_install', '-at_install')
class TestScreenConstraints(common.TransactionCase):

    def test_screen_id_must_be_uppercase_snake(self):
        f = self.env['whatsapp.flow'].create({'name': 'bad_screen'})
        with self.assertRaises(ValidationError):
            self.env['whatsapp.flow.screen'].create({
                'flow_id': f.id, 'screen_id': 'lowercase', 'title': 'X',
            })

    def test_screen_id_unique_per_flow(self):
        f = self.env['whatsapp.flow'].create({'name': 'dup_screen'})
        self.env['whatsapp.flow.screen'].create({
            'flow_id': f.id, 'screen_id': 'ONE', 'title': 'A',
        })
        with self.assertRaises(Exception):
            self.env['whatsapp.flow.screen'].create({
                'flow_id': f.id, 'screen_id': 'ONE', 'title': 'B',
            })
