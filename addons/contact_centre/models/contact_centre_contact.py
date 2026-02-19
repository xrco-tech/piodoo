# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ContactCentreContact(models.Model):
    """
    Contact Centre contact linked to res.partner.
    """
    _name = 'contact.centre.contact'
    _description = 'Contact Centre Contact'
    _rec_name = 'name'

    partner_id = fields.Many2one(
        'res.partner',
        'Partner',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(
        'Name',
        related='partner_id.name',
        store=True,
        readonly=False,
    )
    phone_number = fields.Char(
        'Phone Number',
        related='partner_id.mobile',
        store=True,
        readonly=False,
    )
    last_contact_date = fields.Datetime('Last Contact Date')
    message_ids = fields.One2many(
        'contact.centre.message',
        'contact_id',
        string='Messages',
    )
    campaign_ids = fields.Many2many(
        'contact.centre.campaign',
        'contact_centre_campaign_contact_rel',
        'contact_id',
        'campaign_id',
        string='Campaigns',
    )


class ContactCentreTag(models.Model):
    """Tags for organizing contacts"""
    _name = 'contact.centre.tag'
    _description = 'Contact Centre Tag'

    name = fields.Char('Tag Name', required=True)
    color = fields.Integer('Color', default=1)
    active = fields.Boolean('Active', default=True)
