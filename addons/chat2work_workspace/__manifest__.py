# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work Workspace',
    'version': '18.0.1.7.1',
    'category': 'Human Resources/Recruitment',
    'summary': 'One screen for agents: conversations, candidates, job listings, bookings and an AI sidekick',
    'description': """
Chat2Work Workspace
===================
A single screen for Chat2Work agents, laid out like Discuss: a rail of
sections, a list, the selected record and an information card.

- Conversations: one thread per candidate across WhatsApp, SMS, USSD and the
  CV page, with the stage, callback request, call buttons and a reply box.
- Candidates: the pipeline by stage with follow-up filters, and lists by CV,
  jobs to send and ID check. Running an ID check, its history and the
  VerifyNow credits are on the candidate's information card.
- Job listings: verification and suggested candidates.
- Bookings: interview slots and who is booked into them.
- Sidekick: a chat for agents about candidates, callbacks, CVs, jobs, ID checks
  and how the Workspace works. Lists are counted by the server, how-to answers
  come from the Agent Notes, and it never sends or changes anything.

Uses the existing Chat2Work models and actions. Its own data is each agent's
sidekick chats and the agent notes.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['chat2work', 'chat2work_contact', 'chat2work_jobs', 'chat2work_verify', 'chat2work_ucx'],
    'data': [
        'security/ir.model.access.csv',
        'security/chat2work_workspace_security.xml',
        'views/chat2work_workspace_views.xml',
        'data/chat2work_agent_note_data.xml',
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
