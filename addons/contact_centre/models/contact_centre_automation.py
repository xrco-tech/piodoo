# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ContactCentreAutomation(models.Model):
    _name = 'contact.centre.automation'
    _description = 'Contact Centre Automation'
    _inherit = ['mail.thread']
    _order = 'sequence asc, id asc'

    name = fields.Char('Automation Name', required=True, tracking=True)
    active = fields.Boolean('Active', default=True)
    sequence = fields.Integer('Sequence', default=10)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('both', 'WhatsApp & SMS'),
    ], 'Channel', required=True, tracking=True)
    campaign_id = fields.Many2one('contact.centre.campaign', 'Campaign', ondelete='set null', index=True)

    trigger_type = fields.Selection([
        ('keyword', 'Keyword Match'),
        ('inbound', 'Any Inbound Message'),
        ('first_message', 'First Message'),
        ('no_reply', 'No Reply After Delay'),
    ], 'Trigger', required=True, default='keyword', tracking=True)
    trigger_keyword = fields.Char('Keyword', help='Exact keyword to match (case-insensitive)')

    response_type = fields.Selection([
        ('text', 'Text Reply'),
        ('template', 'Template'),
        ('flow', 'WhatsApp Flow'),
    ], 'Response Type', required=True, default='text', tracking=True)
    response_text = fields.Text('Reply Text')
    template_id = fields.Many2one('contact.centre.template', 'Template',
                                  domain="[('channel', '=', channel)]")

    @api.onchange('trigger_type')
    def _onchange_trigger_type(self):
        if self.trigger_type != 'keyword':
            self.trigger_keyword = False
