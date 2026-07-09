# -*- coding: utf-8 -*-
{
    'name': 'WA Chatbot Test Data',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Sample whatsapp.chatbot flows for smoke-testing the WA engine',
    'description': """
Ships three test chatbots for the legacy comm_whatsapp_chatbot engine:

- Booking Bot — linear message → question_text → question_date →
  confirmation flow. Simplest working example.
- Support Triage — interactive_button question routes to three sub-
  flows (Order / Return / Other). Exercises WA button rendering.
- Feedback Survey — question_text score → question_text comment →
  set_variable → thank you. Exercises variable capture + set_variable.

Each bot ships with status='published' so the simulator runs
immediately. Use the Copy embed code button on any of them to try the
web widget end-to-end.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_whatsapp_chatbot',
        'comm_whatsapp_chatbot_web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/test_wa_bot_booking.xml',
        'data/test_wa_bot_support.xml',
        'data/test_wa_bot_feedback.xml',
    ],
    'installable': True,
    'auto_install': False,
}
