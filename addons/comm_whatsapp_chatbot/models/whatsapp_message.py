# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    # Chatbot fields
    # Note: chatbot_message_ids is not defined here to avoid setup order issues
    # Instead, we search for chatbot messages directly in the compute method
    chatbot_id = fields.Many2one(
        'whatsapp.chatbot',
        string='Chatbot',
        compute='_compute_chatbot_info',
        store=True,
        readonly=True,
        help='Chatbot associated with this message'
    )
    chatbot_name = fields.Char(
        string='Chatbot Name',
        compute='_compute_chatbot_info',
        store=True,
        readonly=True,
        help='Name of the chatbot associated with this message'
    )

    @api.depends('wa_id', 'phone_number', 'message_timestamp', 'is_incoming')
    def _compute_chatbot_info(self):
        """Compute chatbot information from related chatbot messages or active chatbot contact"""
        for record in self:
            chatbot_id = False
            chatbot_name = False
            
            # First, try to get chatbot from direct chatbot message link
            # Use search instead of accessing the One2many to avoid setup issues
            if 'whatsapp.chatbot.message' in self.env:
                chatbot_message = self.env['whatsapp.chatbot.message'].sudo().search([
                    ('wa_message_id', '=', record.id)
                ], limit=1)
                if chatbot_message and chatbot_message.chatbot_id:
                    chatbot_id = chatbot_message.chatbot_id.id
                    chatbot_name = chatbot_message.chatbot_id.name
            
            if not chatbot_id:
                # If no direct link, check if contact is actively engaged with a chatbot
                # This handles messages that are part of an active conversation
                # We check both incoming (wa_id) and outgoing (phone_number) messages
                phone_to_check = record.wa_id if record.is_incoming else (record.phone_number or record.wa_id)
                
                if phone_to_check:
                    # Find contact by phone number
                    partner = self.env['res.partner'].sudo().search([
                        '|',
                        ('phone', '=', phone_to_check),
                        ('mobile', '=', phone_to_check)
                    ], limit=1)
                    
                    if partner:
                        chatbot_contact = self.env['whatsapp.chatbot.contact'].sudo().search([
                            ('partner_id', '=', partner.id),
                            ('last_chatbot_id', '!=', False),
                        ], limit=1, order='last_seen_date desc')
                        
                        if chatbot_contact and chatbot_contact.last_chatbot_id:
                            # Check if last step exists and is not end_flow (still active conversation)
                            if (chatbot_contact.last_step_id and 
                                chatbot_contact.last_step_id.step_type != 'end_flow'):
                                chatbot_id = chatbot_contact.last_chatbot_id.id
                                chatbot_name = chatbot_contact.last_chatbot_id.name
                            # If no last_step but has chatbot, still show it (might be starting conversation)
                            elif not chatbot_contact.last_step_id:
                                chatbot_id = chatbot_contact.last_chatbot_id.id
                                chatbot_name = chatbot_contact.last_chatbot_id.name
            
            record.chatbot_id = chatbot_id
            record.chatbot_name = chatbot_name
