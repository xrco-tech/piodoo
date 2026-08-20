# -*- coding: utf-8 -*-
{
    'name': 'UCX ↔ Contact Centre (Gen-1 inbox)',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Surfaces the Gen-1 Contact Centre inbox inside the UCX app',
    'description': """
UCX ↔ Contact Centre glue
=========================

Optional bridge that adds the original Contact Centre inbox (Gen-1
`contact.centre` data, with the voice-script panel and call picker) back into
the UCX app under Conversations.

This used to be a menu item inside `cx_module` itself, which forced UCX to
depend on `contact_centre_inbox` — a Gen-1 module — purely to expose one
screen. Splitting it out means:

- `cx_module` no longer depends on the Gen-1 inbox at all;
- instances mid-migration can install this and keep both inboxes side by side;
- retiring Gen-1 is just `uninstall cx_module_contact_centre`, with no change
  to UCX.

Deliberately NOT auto_install: the whole point is that surfacing Gen-1 inside
UCX should be an explicit choice, not a side effect of both modules happening
to be present.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': [
        'cx_module',
        'contact_centre_inbox',
    ],
    'data': [
        'views/cx_contact_centre_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
