# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ContactCentreContact(models.Model):
    """
    Enhanced contact model extending res.partner
    Adds contact centre specific fields and functionality
    """
    _inherit = 'res.partner'

    # Communication Channels
    whatsapp_number = fields.Char(
        'WhatsApp Number',
        index=True,
        help='WhatsApp number in international format (e.g., 27683264051)'
    )
    sms_number = fields.Char(
        'SMS Number',
        index=True,
        help='SMS number in international format'
    )
    preferred_channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
    ], 'Preferred Channel', default='whatsapp')

    # Communication History (computed)
    whatsapp_message_count = fields.Integer(
        'WhatsApp Messages',
        compute='_compute_message_counts',
        store=False
    )
    sms_message_count = fields.Integer(
        'SMS Messages',
        compute='_compute_message_counts',
        store=False
    )
    last_whatsapp_message = fields.Datetime(
        'Last WhatsApp',
        compute='_compute_last_message_dates',
        store=False
    )
    last_sms_message = fields.Datetime(
        'Last SMS',
        compute='_compute_last_message_dates',
        store=False
    )

    # Contact Centre Specific
    contact_centre_tags = fields.Many2many(
        'contact.centre.tag',
        'contact_centre_contact_tag_rel',
        'contact_id',
        'tag_id',
        string='Contact Tags'
    )
    assigned_agent_id = fields.Many2one(
        'res.users',
        'Assigned Agent',
        help='Agent currently handling this contact'
    )
    contact_score = fields.Integer(
        'Contact Score',
        default=0,
        help='Engagement score based on interactions'
    )

    # Opt-in/Opt-out
    opt_in_whatsapp = fields.Boolean(
        'WhatsApp Opt-In',
        default=True,
        help='Contact has opted in to receive WhatsApp messages'
    )
    opt_in_sms = fields.Boolean(
        'SMS Opt-In',
        default=True,
        help='Contact has opted in to receive SMS messages'
    )
    opt_out_date = fields.Datetime('Opt-Out Date')

    # Related Records
    whatsapp_message_ids = fields.One2many(
        'contact.centre.message',
        'contact_id',
        string='WhatsApp Messages',
        domain=[('channel', '=', 'whatsapp')]
    )
    sms_message_ids = fields.One2many(
        'contact.centre.message',
        'contact_id',
        string='SMS Messages',
        domain=[('channel', '=', 'sms')]
    )
    campaign_ids = fields.Many2many(
        'contact.centre.campaign',
        'contact_centre_campaign_contact_rel',
        'contact_id',
        'campaign_id',
        string='Campaigns'
    )

    @api.depends('whatsapp_message_ids', 'sms_message_ids')
    def _compute_message_counts(self):
        """Compute message counts per channel"""
        for contact in self:
            contact.whatsapp_message_count = len(contact.whatsapp_message_ids)
            contact.sms_message_count = len(contact.sms_message_ids)

    @api.depends('whatsapp_message_ids.message_timestamp', 'sms_message_ids.message_timestamp')
    def _compute_last_message_dates(self):
        """Compute last message dates per channel"""
        for contact in self:
            whatsapp_messages = contact.whatsapp_message_ids.sorted('message_timestamp', reverse=True)
            sms_messages = contact.sms_message_ids.sorted('message_timestamp', reverse=True)
            contact.last_whatsapp_message = whatsapp_messages[0].message_timestamp if whatsapp_messages else False
            contact.last_sms_message = sms_messages[0].message_timestamp if sms_messages else False

    def send_whatsapp_message(self, message_body, **kwargs):
        """
        Send WhatsApp message to this contact
        TODO: Implement WhatsApp sending logic
        """
        self.ensure_one()
        if not self.whatsapp_number:
            raise ValueError("Contact does not have a WhatsApp number")
        if not self.opt_in_whatsapp:
            raise ValueError("Contact has opted out of WhatsApp messages")
        
        # TODO: Create contact.centre.message record and send via API
        _logger.info(f"Sending WhatsApp message to {self.whatsapp_number}: {message_body}")
        return True

    def send_sms_message(self, message_body, **kwargs):
        """
        Send SMS message to this contact
        TODO: Implement SMS sending logic
        """
        self.ensure_one()
        if not self.sms_number:
            raise ValueError("Contact does not have an SMS number")
        if not self.opt_in_sms:
            raise ValueError("Contact has opted out of SMS messages")
        
        # TODO: Create contact.centre.message record and send via API
        _logger.info(f"Sending SMS message to {self.sms_number}: {message_body}")
        return True

    def get_conversation_history(self, channel=None, limit=50):
        """
        Get unified conversation history for this contact
        :param channel: Filter by channel ('whatsapp', 'sms', or None for all)
        :param limit: Maximum number of messages to return
        :return: recordset of contact.centre.message
        """
        self.ensure_one()
        domain = [('contact_id', '=', self.id)]
        if channel:
            domain.append(('channel', '=', channel))
        
        return self.env['contact.centre.message'].search(
            domain,
            order='message_timestamp desc',
            limit=limit
        )


class ContactCentreTag(models.Model):
    """Tags for organizing contacts"""
    _name = 'contact.centre.tag'
    _description = 'Contact Centre Tag'

    name = fields.Char('Tag Name', required=True)
    color = fields.Integer('Color', default=1)
    active = fields.Boolean('Active', default=True)
