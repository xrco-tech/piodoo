# -*- coding: utf-8 -*-
{
    'name': 'Comms Test Data',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Sample partners / bots / campaigns / activity for exercising the comms stack',
    'description': """
Comms Test Data
===============

Installable seed pack for exercising the omni-channel comms platform end
to end without touching production data:

- 10 test partners across reachability profiles (WA + phone + email,
  SMS-only, opted-out, international)
- Per-channel communication preferences matrix
- 4 bots covering:
    * Booking flow (menu → date input → condition → confirmation)
    * Customer service (LLM step with tools + decision output)
    * Onboarding A + Onboarding B (A/B variants for the same campaign)
- 4 campaigns in each lifecycle state (draft, running with variants,
  completed with conversions, paused)
- Historical conversations, interactions, and billing events via
  post_init hook — populates dashboards + graphs with realistic
  variety (WA, SMS, USSD, voice, LLM)

Uninstall to remove all test data cleanly. Do not install on prod.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_chatbot',
        'comm_chatbot_whatsapp',
        'comm_chatbot_sms',
        'comm_chatbot_ussd',
        'comm_chatbot_voice',
        'comm_chatbot_web',
        'comm_chatbot_starter',
        'comm_campaign',
        'comm_whatsapp_billing',
        'comm_sms_billing',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/test_partners_data.xml',
        'data/test_communication_prefs_data.xml',
        'data/test_bot_booking.xml',
        'data/test_bot_customer_service.xml',
        'data/test_bots_ab.xml',
        'data/test_bot_faq_web.xml',
        'data/test_bot_survey.xml',
        'data/test_campaigns_data.xml',
    ],
    'post_init_hook': 'generate_historical_activity',
    'installable': True,
    'auto_install': False,
}
