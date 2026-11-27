# -*- coding: utf-8 -*-
{
    'name': 'AI Agents',
    'version': '18.0.1.1.3',
    'category': 'Productivity',
    'summary': 'Every assistant in piodoo in one place: what it is told and what it costs',
    'description': """
AI Agents
=========
One screen for the assistants that already work inside piodoo.

- Home: each assistant as a card, with where it works, the model it runs on
  and its runs and cost over the last 30 days.
- One agent: chat with it (the two Sidekicks), or see its runs by day, and
  read or change what it is told. Every change is kept and can be put back.
- Skills: switch off a group of an agent's tools. Knowledge: narrow what it
  reads from the Library. Triggers: the timers it runs on. Limits: its model,
  a monthly spending limit and a limit for one answer.

The assistants stay in their own add-ons. Each one asks this app for its
wording, so nothing here is needed for them to run, and only the ones whose
add-on is installed are shown. Tools, checks and limits stay in code.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'data/piodoo_ai_agent_data.xml',
        'views/piodoo_ai_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'piodoo_ai/static/src/app/agents.scss',
            'piodoo_ai/static/src/app/agents.js',
            'piodoo_ai/static/src/app/agents.xml',
        ],
        'web.assets_web_dark': [
            'piodoo_ai/static/src/app/agents.dark.scss',
        ],
    },
    'application': True,
    'installable': True,
}
