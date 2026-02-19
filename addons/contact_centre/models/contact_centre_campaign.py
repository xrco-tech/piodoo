# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ContactCentreCampaign(models.Model):
    """Campaign model - TODO: Implement"""
    _name = 'contact.centre.campaign'
    _description = 'Contact Centre Campaign'

    name = fields.Char('Campaign Name', required=True)
    campaign_type = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], 'Type', required=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('both', 'WhatsApp & SMS'),
    ], 'Channel', required=True)
    contact_ids = fields.Many2many(
        'contact.centre.contact',
        'contact_centre_campaign_contact_rel',
        'campaign_id',
        'contact_id',
        string='Contacts',
    )
