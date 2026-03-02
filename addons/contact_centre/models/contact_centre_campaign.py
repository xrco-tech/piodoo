# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ContactCentreCampaign(models.Model):
    _name = 'contact.centre.campaign'
    _description = 'Contact Centre Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char('Campaign Name', required=True, tracking=True)
    active = fields.Boolean('Active', default=True)
    description = fields.Text('Description')
    campaign_type = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], 'Type', required=True, tracking=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('both', 'WhatsApp & SMS'),
    ], 'Channel', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], 'Status', default='draft', tracking=True)
    date_start = fields.Datetime('Start Date', tracking=True)
    date_end = fields.Datetime('End Date', tracking=True)

    contact_ids = fields.Many2many(
        'contact.centre.contact',
        'contact_centre_campaign_contact_rel',
        'campaign_id',
        'contact_id',
        string='Contacts',
    )
    message_ids = fields.One2many(
        'contact.centre.message',
        'campaign_id',
        string='Messages',
    )
    template_id = fields.Many2one(
        'contact.centre.template',
        'Message Template',
        domain="[('channel', '=', channel)]",
    )
    script_id = fields.Many2one(
        'contact.centre.script',
        'Agent Script',
    )
    automation_ids = fields.One2many(
        'contact.centre.automation',
        'campaign_id',
        string='Automated Replies',
    )

    contact_count = fields.Integer('Contacts', compute='_compute_counts')
    message_count = fields.Integer('Messages', compute='_compute_counts')
    sent_count = fields.Integer('Sent', compute='_compute_counts')
    delivered_count = fields.Integer('Delivered', compute='_compute_counts')
    failed_count = fields.Integer('Failed', compute='_compute_counts')

    @api.depends('contact_ids', 'message_ids')
    def _compute_counts(self):
        for campaign in self:
            campaign.contact_count = len(campaign.contact_ids)
            campaign.message_count = len(campaign.message_ids)
            campaign.sent_count = len(campaign.message_ids.filtered(lambda m: m.status in ('sent', 'delivered', 'read')))
            campaign.delivered_count = len(campaign.message_ids.filtered(lambda m: m.status in ('delivered', 'read')))
            campaign.failed_count = len(campaign.message_ids.filtered(lambda m: m.status == 'failed'))

    def action_start(self):
        self.write({'state': 'running', 'date_start': fields.Datetime.now()})

    def action_done(self):
        self.write({'state': 'done', 'date_end': fields.Datetime.now()})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})
