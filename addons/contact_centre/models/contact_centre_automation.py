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

    # -------------------------------------------------------------------------
    # Execution — called by the webhook controller when no chatbot handled
    # the inbound message (contact.centre.chatbot.route_inbound returned False)
    # -------------------------------------------------------------------------

    @api.model
    def check_and_fire(self, contact, channel, body, cc_message=None):
        """Find the first matching active automation for this inbound
        message and fire it. Returns True if one fired, False otherwise."""
        domain = [
            ('active', '=', True),
            ('trigger_type', '!=', 'no_reply'),
            '|', ('channel', '=', channel), ('channel', '=', 'both'),
        ]
        body_normalized = (body or '').strip().lower()
        is_first_message = len(contact.centre_message_ids) == 1

        for automation in self.search(domain, order='sequence asc, id asc'):
            if automation.trigger_type == 'keyword':
                if not automation.trigger_keyword or \
                        automation.trigger_keyword.strip().lower() != body_normalized:
                    continue
            elif automation.trigger_type == 'first_message':
                if not is_first_message:
                    continue
            elif automation.trigger_type != 'inbound':
                continue
            return automation._fire(contact, channel)
        return False

    def _fire(self, contact, channel):
        self.ensure_one()
        if self.response_type == 'text':
            body = self.response_text or ''
        elif self.response_type == 'template':
            body = self.template_id.body_text or ''
        else:
            _logger.warning(
                "Automation %s: response_type 'flow' is not implemented, skipping.", self.name)
            return False
        if not body:
            return False

        if channel == 'whatsapp':
            self._fire_whatsapp(contact, body)
        elif channel == 'sms':
            self._fire_sms(contact, body)
        else:
            return False
        return True

    def _fire_whatsapp(self, contact, body):
        phone = contact.phone_number
        bsuid = contact.bsuid
        if not phone and not bsuid:
            _logger.warning(
                "Automation %s: contact %s has no phone number or WhatsApp ID, skipping WA.",
                self.name, contact.id)
            return

        account = self.env['comm.whatsapp.account'].sudo().get_default()
        result = self.env['whatsapp.message'].sudo().send_whatsapp_message(
            recipient_phone=phone,
            message_text=body,
            account=account,
            bsuid=bsuid,
        )
        success = isinstance(result, dict) and result.get('success', False)
        status = 'sent' if success else 'failed'
        failure = result.get('error', '') if isinstance(result, dict) and not success else ''

        self.env['contact.centre.message'].sudo().create({
            'contact_id': contact.id,
            'automation_id': self.id,
            'channel': 'whatsapp',
            'direction': 'outbound',
            'message_type': 'text',
            'body_text': body,
            'status': status,
            'failure_reason': failure,
            'provider_message_id': result.get('message_id', '') if isinstance(result, dict) else '',
            'template_id': self.template_id.id if self.response_type == 'template' else False,
            'message_timestamp': fields.Datetime.now(),
        })

    def _fire_sms(self, contact, body):
        phone = contact.phone_number
        if not phone:
            _logger.warning("Automation %s: contact %s has no phone number, skipping SMS.",
                             self.name, contact.id)
            return

        sms = self.env['sms.sms'].sudo().create({
            'number': phone,
            'body': body,
            'state': 'outgoing',
        })
        try:
            sms._send()
            status = 'sent'
            failure = ''
        except Exception as e:
            status = 'failed'
            failure = str(e)

        self.env['contact.centre.message'].sudo().create({
            'contact_id': contact.id,
            'automation_id': self.id,
            'channel': 'sms',
            'direction': 'outbound',
            'message_type': 'text',
            'body_text': body,
            'status': status,
            'failure_reason': failure,
            'template_id': self.template_id.id if self.response_type == 'template' else False,
            'message_timestamp': fields.Datetime.now(),
        })
