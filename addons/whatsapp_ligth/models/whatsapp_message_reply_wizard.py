# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsAppMessageReplyWizard(models.TransientModel):
    _name = 'whatsapp.message.reply.wizard'
    _description = 'WhatsApp Message Reply Wizard'

    message_id = fields.Many2one('whatsapp.message', string='Original Message', required=True, readonly=True)
    recipient_phone = fields.Char(string='Recipient Phone', required=True, readonly=True, 
                                  help='Phone number in international format (e.g., 27683264051)')
    phone_number_id = fields.Char(string='Phone Number ID', readonly=True, 
                                  help='Meta phone number ID to use for sending')
    reply_text = fields.Text(string='Reply Message', required=True, 
                            help='Message to send as reply')
    
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('default_message_id'):
            message = self.env['whatsapp.message'].browse(self.env.context['default_message_id'])
            res['message_id'] = message.id
            res['recipient_phone'] = message.wa_id
            # Use phone_number_id from message, or fallback to system parameter
            phone_number_id = message.phone_number_id
            if not phone_number_id:
                IrConfigParameter = self.env['ir.config_parameter'].sudo()
                phone_number_id = IrConfigParameter.get_param('whatsapp_ligth.phone_number_id')
            res['phone_number_id'] = phone_number_id
        return res

    def action_send_reply(self):
        """
        Send the reply message via WhatsApp API.
        """
        self.ensure_one()
        
        if not self.reply_text.strip():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Please enter a message to send.',
                    'type': 'danger',
                    'sticky': False,
                }
            }
        
        # Send message using the model method
        result = self.env['whatsapp.message'].send_whatsapp_message(
            recipient_phone=self.recipient_phone,
            message_text=self.reply_text,
            phone_number_id=self.phone_number_id
        )
        
        if result.get('success'):
            # Update original message status
            if self.message_id:
                self.message_id.write({'status': 'replied'})
            
            # Return action that shows notification and closes wizard
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': f'Message sent successfully! Message ID: {result.get("message_id", "N/A")}',
                    'type': 'success',
                    'sticky': False,
                },
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Failed to send message: {result.get("error", "Unknown error")}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

