# -*- coding: utf-8 -*-

import logging
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ContactCentreMessage(models.Model):
    _name = 'contact.centre.message'
    _description = 'Contact Centre Message'
    _order = 'message_timestamp desc, id desc'

    name = fields.Char('Message ID', required=True, index=True, copy=False,
                       default=lambda self: self.env['ir.sequence'].next_by_code('contact.centre.message'))
    contact_id = fields.Many2one('contact.centre.contact', 'Contact', required=True, index=True, ondelete='cascade')
    campaign_id = fields.Many2one('contact.centre.campaign', 'Campaign', index=True, ondelete='set null')
    assigned_user_id = fields.Many2one('res.users', 'Assigned Agent', index=True)

    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
    ], 'Channel', required=True, index=True)
    direction = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], 'Direction', required=True, index=True)
    message_type = fields.Selection([
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
        ('location', 'Location'),
        ('template', 'Template'),
        ('interactive', 'Interactive'),
    ], 'Message Type', default='text')
    body_text = fields.Text('Message Body')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ], 'Status', default='pending', index=True)
    failure_reason = fields.Char('Failure Reason')
    message_timestamp = fields.Datetime('Message Time', required=True, index=True,
                                        default=fields.Datetime.now)

    # Provider-specific tracking
    provider_message_id = fields.Char('Provider Message ID', index=True,
                                      help='Message ID from WhatsApp/InfoBip/etc.')

    # WhatsApp-specific
    whatsapp_message_id = fields.Many2one('whatsapp.message', 'WhatsApp Message',
                                          ondelete='set null', index=True)

    # SMS-specific
    sms_id = fields.Many2one('sms.sms', 'SMS Record', ondelete='set null', index=True)

    # Template used
    template_id = fields.Many2one('contact.centre.template', 'Template Used', ondelete='set null')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('contact.centre.message') or '/'
        records = super().create(vals_list)
        # Update last contact date on the contact
        for record in records:
            record.contact_id.write({'last_contact_date': record.message_timestamp})
        return records

    @api.model
    def get_response_time_stats(self, days=30):
        """Average time between each inbound message and the next outbound
        reply from the same contact, across all such pairs in the window."""
        since = fields.Datetime.now() - timedelta(days=days)
        messages = self.search([
            ('message_timestamp', '>=', since),
        ], order='contact_id, message_timestamp asc')

        first_inbound = {}
        deltas = []
        for message in messages:
            contact_id = message.contact_id.id
            if message.direction == 'inbound':
                first_inbound.setdefault(contact_id, message.message_timestamp)
            elif message.direction == 'outbound' and contact_id in first_inbound:
                inbound_time = first_inbound.pop(contact_id)
                deltas.append((message.message_timestamp - inbound_time).total_seconds())

        if not deltas:
            return {'avg_seconds': None, 'sample_size': 0}
        return {'avg_seconds': sum(deltas) / len(deltas), 'sample_size': len(deltas)}
