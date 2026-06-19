# -*- coding: utf-8 -*-

# Import chatbot models first so they exist when whatsapp_message extension references them
from . import whatsapp_chatbot
from . import whatsapp_chatbot_step
from . import whatsapp_chatbot_contact
from . import whatsapp_chatbot_message
from . import whatsapp_chatbot_variable
from . import whatsapp_chatbot_answer
from . import whatsapp_chatbot_global_interrupt
from . import whatsapp_chatbot_ussd_session
# Import whatsapp_message extension last since it depends on chatbot models
from . import whatsapp_message

