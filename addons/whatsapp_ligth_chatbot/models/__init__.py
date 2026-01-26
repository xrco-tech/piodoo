# -*- coding: utf-8 -*-

# Import chatbot models first so they exist when whatsapp_message extension references them
from . import whatsapp_chatbot
from . import whatsapp_chatbot_step
from . import whatsapp_chatbot_contact
from . import whatsapp_chatbot_message
from . import whatsapp_chatbot_variable
from . import whatsapp_chatbot_answer
# Import whatsapp_message extension last since it depends on chatbot models
from . import whatsapp_message

