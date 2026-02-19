# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ContactCentreMessage(models.Model):
    """
    Unified message model for WhatsApp and SMS
    TODO: Implement full message functionality
    """
    _name = 'contact.centre.message'
    _description = 'Contact Centre Message'
    _order = 'message_timestamp desc, id desc'

    name = fields.Char('Message ID', required=True, index=True)
    contact_id = fields.Many2one('contact.centre.contact', 'Contact', required=True, index=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
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
    ], 'Message Type', default='text')
    body_text = fields.Text('Message Body')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ], 'Status', default='pending')
    message_timestamp = fields.Datetime('Message Time', required=True, index=True)
