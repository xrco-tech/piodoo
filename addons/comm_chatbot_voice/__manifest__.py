# -*- coding: utf-8 -*-
{
    'name': 'Comm Chatbot — Voice Adapter',
    'version': '18.0.1.0.1',
    'category': 'Communications',
    'summary': 'Voice channel adapter for comm_chatbot (TTS/DTMF + streaming)',
    'author': 'XR Co.',
    'license': 'LGPL-3',
    # The adapter only imports from comm_chatbot.models.runtime and registers a
    # 'voice' adapter — it never touches the legacy whatsapp.chatbot models, so
    # the comm_whatsapp_chatbot dependency was vestigial. Dropped to keep the
    # Gen-2 channel graph free of Gen-1 coupling (needed for UCX/cx_module).
    'depends': ['comm_chatbot'],
    'data': ['security/ir.model.access.csv'],
    'installable': True,
    'auto_install': False,
}
