# -*- coding: utf-8 -*-
{
    'name': 'Communication Chatbot Engine',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Channel-agnostic bot engine — WhatsApp, SMS, USSD, voice, LLM',
    'description': """
Communication Chatbot Engine
============================

A single bot script runs on every channel via pluggable adapters:

- **Design-time**: comm.bot with steps (message / menu / input / condition /
  action / handoff / llm / jump / wait / end / channel_switch), per-channel
  overrides, variables, triggers.
- **Runtime**: comm.conversation (cross-channel, contact-centric) with per-
  channel legs and canonical interaction log.
- **Renderer**: capability-degrading pipeline — same script produces buttons
  on WA, numbered menu on USSD, TTS + DTMF on voice.
- **LLM step** as first-class primitive with tool loop, structured output,
  streaming for voice, prompt caching, cost guardrails.
- **Adapter registry**: channel modules register a Python class; engine
  discovers them at load time.

Channel adapters are separate installable modules:
  comm_chatbot_whatsapp, comm_chatbot_sms, comm_chatbot_ussd, comm_chatbot_voice.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'contacts',
        'comm_billing_core',
    ],
    'data': [
        'security/comm_chatbot_groups.xml',
        'security/ir.model.access.csv',
        'data/comm_channel_data.xml',
        'data/ir_cron_data.xml',
        'views/comm_channel_views.xml',
        'views/comm_bot_views.xml',
        'views/comm_bot_step_views.xml',
        'views/comm_bot_trigger_views.xml',
        'views/comm_bot_llm_tool_views.xml',
        'views/comm_conversation_views.xml',
        'views/comm_interaction_views.xml',
        'views/comm_chatbot_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
