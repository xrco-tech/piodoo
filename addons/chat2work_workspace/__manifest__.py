# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work Workspace',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'One screen for agents: conversations, candidates, job listings, bookings and ID checks',
    'description': """
Chat2Work Workspace
===================
A single screen for Chat2Work agents, laid out like Discuss: a rail of
sections, a list, the selected record and an information card.

- Conversations: one thread per candidate across WhatsApp, SMS, USSD and the
  CV page, with the stage, callback request, call buttons and a reply box.
- Candidates: the pipeline by stage, with follow-up filters.
- Job listings: verification and suggested candidates.
- Bookings: interview slots and who is booked into them.
- ID checks: the check history, Home Affairs details and credits.

Uses the existing Chat2Work models and actions; it adds no data of its own.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['chat2work', 'chat2work_contact', 'chat2work_jobs', 'chat2work_verify', 'chat2work_ucx'],
    'data': [
        'views/chat2work_workspace_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'chat2work_workspace/static/src/workspace/workspace.scss',
            'chat2work_workspace/static/src/workspace/workspace.js',
            'chat2work_workspace/static/src/workspace/workspace.xml',
        ],
        'web.assets_web_dark': [
            'chat2work_workspace/static/src/workspace/workspace.dark.scss',
        ],
    },
    'installable': True,
}
