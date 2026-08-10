# -*- coding: utf-8 -*-

from odoo import api, fields, models


class CommVoipAccount(models.Model):
    _name = 'comm.voip.account'
    _description = 'VoIP Account / Provider Config'
    _order = 'sequence, id'
    _rec_name = 'name'

    name = fields.Char('Display Name', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean('Default Account')

    provider = fields.Selection([
        ('infobip', 'Infobip Voice'),
        ('sip', 'SIP Trunk / PBX'),
        ('twilio', 'Twilio'),
        ('other', 'Other'),
    ], string='Provider', default='other', required=True)

    # Cloud-API providers (Infobip / Twilio / other HTTP).
    base_url = fields.Char('API Base URL')
    api_key = fields.Char('API Key / Auth Token')
    caller_id = fields.Char('Caller ID / From Number',
                            help="The number/ID shown to the person being called.")

    # SIP trunk / PBX credentials (used when provider = sip).
    sip_domain = fields.Char('SIP Domain')
    sip_username = fields.Char('SIP Username')
    sip_password = fields.Char('SIP Password')

    webhook_hint = fields.Char(
        'Inbound Webhook', compute='_compute_webhook_hint',
        help="Point your provider's inbound-call webhook here (once the "
             "provider send/receive is wired).")
    call_count = fields.Integer('Calls', compute='_compute_call_count')

    def _compute_webhook_hint(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        for rec in self:
            rec.webhook_hint = '%s/voip/inbound' % base if base else '/voip/inbound'

    def _compute_call_count(self):
        Call = self.env['comm.voip.call']
        for rec in self:
            rec.call_count = Call.search_count([('account_id', '=', rec.id)])

    @api.model
    def get_default(self):
        return self.search([('active', '=', True), ('is_default', '=', True)], limit=1) \
            or self.search([('active', '=', True)], limit=1)
