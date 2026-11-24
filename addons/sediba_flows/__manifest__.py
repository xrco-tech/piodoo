# -*- coding: utf-8 -*-
{
    'name': 'Sediba Flows',
    'version': '18.0.1.11.1',
    'category': 'Communications',
    'summary': 'Design a conversation once and run it on any connected channel',
    'description': """
Sediba Flows
============
A flow builder that is its own app and is not tied to any one channel.

- Flows: every flow in one list, with the channels it runs on, its number of
  steps and whether it is live.
- Builder: steps are cards on a canvas that place themselves. A step is
  written once (Message, Menu, Question, Condition, Action, AI reply,
  Hand-over, Go to flow, Wait, End); you say which step comes next, you never
  draw lines.
- How it comes out: for the selected step, what each channel of the flow will
  send (reply buttons, a numbered list, read out) and a warning when
  something will not fit, for example a text too long for one USSD screen.
  A step can have different wording for one channel, or be skipped there.
- Try it: walk the flow as a contact on a chosen channel. Nothing is sent.

It sits on the channel-agnostic bot engine (comm_chatbot) and needs no
channel add-on: the channels shown are the ones installed.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': ['web', 'comm_chatbot'],
    'data': [
        'views/sediba_flows_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sediba_flows/static/src/app/flows.scss',
            'sediba_flows/static/src/app/flows.js',
            'sediba_flows/static/src/app/flows.xml',
        ],
        'web.assets_web_dark': [
            'sediba_flows/static/src/app/flows.dark.scss',
        ],
    },
    'application': True,
    'installable': True,
}
