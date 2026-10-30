# -*- coding: utf-8 -*-
"""Send one WhatsApp message or SMS to a candidate, typed or from a template.

Template choices are dynamic selections read with sudo, so agents can message
candidates without having WhatsApp administration rights.
"""

import math
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.chat2work.models.chat2work import _send_sms

SERVICE_WINDOW_HOURS = 24
PLACEHOLDER = re.compile(r'\{\{(\d+)\}\}')
SMS_SINGLE = 160
SMS_PART = 153


class Chat2workMessage(models.TransientModel):
    _name = 'chat2work.message'
    _description = 'Message a Chat2Work Candidate'

    candidate_id = fields.Many2one('chat2work.candidate', required=True, ondelete='cascade')
    phone = fields.Char(related='candidate_id.phone')
    uses_whatsapp = fields.Boolean(related='candidate_id.whatsapp_opt_in')
    channel = fields.Selection([('whatsapp', 'WhatsApp'), ('sms', 'SMS')], required=True,
                               default=lambda self: self._default_channel())
    window_open = fields.Boolean(compute='_compute_window_open')
    use_template = fields.Boolean('Use a template')
    wa_template = fields.Selection(selection='_wa_template_options', string='WhatsApp Template')
    sms_template = fields.Selection(selection='_sms_template_options', string='SMS Template')
    param_ids = fields.One2many('chat2work.message.param', 'message_id', 'Template Values')
    body = fields.Text('Message')
    preview = fields.Text(compute='_compute_preview')
    sms_length = fields.Char(compute='_compute_sms_length')

    # ── Options ──────────────────────────────────────────────────────────────

    def _default_channel(self):
        candidate = self.env['chat2work.candidate'].browse(self.env.context.get('default_candidate_id')).exists()
        return 'whatsapp' if candidate.whatsapp_opt_in else 'sms'

    @api.model
    def _sendable_wa_templates(self):
        """Approved templates this form can fill in: only body values are asked
        for, so ones with a variable header or link can't be sent from here."""
        Template = self.env['whatsapp.template'].sudo()
        account = self.env['comm.whatsapp.account'].sudo().search([], order='id', limit=1)
        only = self.env['ir.config_parameter'].sudo().get_param('chat2work.wa_phone_number_id')
        if only:
            account = account.search([('phone_number_id', '=', only)], limit=1)
        templates = Template.search([('status', '=', 'APPROVED'), ('account_id', '=', account.id)], order='name')
        return templates.filtered(lambda t: '{{' not in (t.header_text or '') and not any(
            '{{' in (b.url or '') or b.button_type == 'FLOW' for b in t.button_ids))

    @api.model
    def _wa_template_options(self):
        return [(str(t.id), '%s (%s)' % (t.name, t.category)) for t in self._sendable_wa_templates()]

    @api.model
    def _sms_template_options(self):
        templates = self.env['sms.template'].sudo().search([('model', '=', 'chat2work.candidate')], order='name')
        return [(str(t.id), t.name) for t in templates]

    # ── Form behaviour ───────────────────────────────────────────────────────

    def _wa_template_record(self):
        self.ensure_one()
        return self.env['whatsapp.template'].sudo().browse(int(self.wa_template)) if self.wa_template \
            else self.env['whatsapp.template']

    @api.depends('candidate_id')
    def _compute_window_open(self):
        """WhatsApp only allows typed messages within 24 hours of their last message."""
        cutoff = fields.Datetime.now() - timedelta(hours=SERVICE_WINDOW_HOURS)
        Message = self.env['whatsapp.message'].sudo()
        for rec in self:
            digits = re.sub(r'\D', '', rec.candidate_id.phone or '')
            rec.window_open = bool(digits) and bool(Message.search_count([
                ('wa_id', '=', digits), ('is_incoming', '=', True), ('message_timestamp', '>=', cutoff),
            ], limit=1))

    @api.onchange('channel', 'candidate_id')
    def _onchange_channel(self):
        if self.channel == 'whatsapp' and not self.window_open:
            self.use_template = True

    @api.onchange('wa_template')
    def _onchange_wa_template(self):
        template = self._wa_template_record()
        first_name = (self.candidate_id.name or '').split(' ')[0]
        lines = [(5, 0, 0)]
        for number in sorted({int(n) for n in PLACEHOLDER.findall(template.body or '')}):
            lines.append((0, 0, {'number': number, 'value': first_name if number == 1 else ''}))
        self.param_ids = lines

    @api.onchange('sms_template')
    def _onchange_sms_template(self):
        if self.sms_template:
            template = self.env['sms.template'].sudo().browse(int(self.sms_template))
            self.body = template._render_field('body', self.candidate_id.ids)[self.candidate_id.id]

    @api.depends('channel', 'use_template', 'wa_template', 'param_ids.value')
    def _compute_preview(self):
        for rec in self:
            text = False
            if rec.channel == 'whatsapp' and rec.use_template and rec.wa_template:
                values = {str(p.number): p.value or '{{%d}}' % p.number for p in rec.param_ids}
                text = PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)),
                                       rec._wa_template_record().body or '')
            rec.preview = text

    @api.depends('body')
    def _compute_sms_length(self):
        for rec in self:
            size = len(rec.body or '')
            parts = 1 if size <= SMS_SINGLE else math.ceil(size / SMS_PART)
            rec.sms_length = _("%(size)s characters, %(parts)s SMS", size=size, parts=parts)

    # ── Sending ──────────────────────────────────────────────────────────────

    def action_send(self):
        self.ensure_one()
        candidate = self.candidate_id
        if self.channel == 'sms':
            self._send_sms()
        elif not candidate.whatsapp_opt_in:
            raise UserError(_("This candidate hasn't said they use WhatsApp. Send an SMS instead."))
        elif self.use_template:
            self._send_wa_template()
        else:
            self._send_wa_text()
        return {'type': 'ir.actions.act_window_close'}

    def _note(self, channel_label, channel, text):
        candidate = self.candidate_id
        candidate.message_post(body=_("%(channel)s sent: %(text)s", channel=channel_label, text=text))
        candidate._c2w_log_event(channel, 'outbound', text, status='sent')

    def _send_sms(self):
        text = (self.body or '').strip()
        if not text:
            raise UserError(_("Type a message or choose a template."))
        if not _send_sms(self.env, self.candidate_id.phone, text):
            raise UserError(_("The SMS couldn't be sent. Please try again."))
        self._note(_("SMS"), 'sms', text)

    def _send_wa_text(self):
        text = (self.body or '').strip()
        if not text:
            raise UserError(_("Type a message."))
        if not self.window_open:
            raise UserError(_("It's more than 24 hours since this candidate messaged you, so WhatsApp "
                              "only allows a template."))
        digits = re.sub(r'\D', '', self.candidate_id.phone)
        result = self.env['whatsapp.message'].sudo().send_whatsapp_payload(
            digits, {'type': 'text', 'text': {'body': text}}, log_body=text, log_type='text')
        if not result.get('success'):
            raise UserError(_("WhatsApp didn't accept the message: %s", result.get('error') or _("unknown error")))
        self._note(_("WhatsApp"), 'whatsapp', text)

    def _send_wa_template(self):
        template = self._wa_template_record()
        if not template or template not in self._sendable_wa_templates():
            raise UserError(_("Choose a template."))
        if any(not (p.value or '').strip() for p in self.param_ids):
            raise UserError(_("Fill in all the template values."))
        Sender = self.env['whatsapp.template.send.wizard'].sudo()
        sender = Sender.with_context(default_template_id=template.id).create({
            'template_id': template.id,
            'recipient_phone': re.sub(r'\D', '', self.candidate_id.phone),
            'parameter_ids': [(5, 0, 0)] + [(0, 0, {
                'sequence': p.number, 'placeholder': '{{%d}}' % p.number, 'value': p.value.strip(),
            }) for p in self.param_ids.sorted('number')],
        })
        result = sender.action_send_template()
        if (result or {}).get('type') != 'ir.actions.act_window_close':
            raise UserError(((result or {}).get('params') or {}).get('message') or _("The template wasn't sent."))
        self._note(_("WhatsApp template %s", template.name), 'whatsapp', self.preview or template.body)


class Chat2workMessageParam(models.TransientModel):
    _name = 'chat2work.message.param'
    _description = 'Template Value'
    _order = 'number'

    message_id = fields.Many2one('chat2work.message', required=True, ondelete='cascade')
    number = fields.Integer(readonly=True)
    label = fields.Char('Placeholder', compute='_compute_label')
    value = fields.Char()

    @api.depends('number')
    def _compute_label(self):
        for rec in self:
            rec.label = '{{%d}}' % rec.number
