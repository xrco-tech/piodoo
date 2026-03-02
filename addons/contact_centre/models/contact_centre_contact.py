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
    email = fields.Char(
        'Email',
        related='partner_id.email',
        store=True,
        readonly=False,
    )
    last_contact_date = fields.Datetime('Last Contact Date')
    tag_ids = fields.Many2many(
        'contact.centre.tag',
        'contact_centre_contact_tag_rel',
        'contact_id',
        'tag_id',
        string='Tags',
    )
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
    message_count = fields.Integer('Message Count', compute='_compute_message_count')

    @api.depends('message_ids')
    def _compute_message_count(self):
        for contact in self:
            contact.message_count = len(contact.message_ids)


class ContactCentreTag(models.Model):
    """Tags for organizing contacts"""
    _name = 'contact.centre.tag'
    _description = 'Contact Centre Tag'

    name = fields.Char('Tag Name', required=True)
    color = fields.Integer('Color', default=1)
    active = fields.Boolean('Active', default=True)
