# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.chat2work.models.chat2work_ussd import msisdn_variants


class Chat2workCandidateContact(models.Model):
    _inherit = 'chat2work.candidate'

    c2w_can_voip = fields.Boolean(compute='_compute_c2w_can_voip')
    c2w_call_permission = fields.Selection(
        lambda self: self.env['whatsapp.call.permission']._fields['state'].selection,
        'WhatsApp Call Permission', compute='_compute_c2w_call_permission')
    c2w_call_permission_note = fields.Char(compute='_compute_c2w_call_permission')

    def _compute_c2w_can_voip(self):
        can = bool(self.env.user.sudo().dialer_sip_ext)
        for rec in self:
            rec.c2w_can_voip = can

    @api.depends('phone', 'name')
    def _compute_c2w_call_permission(self):
        Permission = self.env['whatsapp.call.permission']
        for rec in self:
            status = Permission._status_for(rec.phone, name=rec.name) if rec.phone else {}
            rec.c2w_call_permission = status.get('state') or False
            rec.c2w_call_permission_note = status.get('message') or False

    def action_c2w_request_call_permission(self):
        self._c2w_require_phone()
        result = self.env['whatsapp.call.permission']._send_request(
            self.phone, partner_name=self.name, partner_id=self.partner_id.id)
        if not result.get('success'):
            raise UserError(_("No approved call permission template is available.")
                            if result.get('error') == 'template_missing'
                            else _("The request couldn't be sent: %s", result.get('error')))
        return True

    def _c2w_require_phone(self):
        self.ensure_one()
        if not self.phone:
            raise UserError(_("This candidate has no phone number."))

    def action_c2w_call_whatsapp(self):
        self._c2w_require_phone()
        if not self.whatsapp_opt_in:
            raise UserError(_("This candidate hasn't said they use WhatsApp."))
        self.message_post(body=_("WhatsApp call attempted."))
        return {
            'type': 'ir.actions.client',
            'tag': 'comm_whatsapp_calling.dial',
            'params': {
                'to_number': self.phone,
                'partner_id': self.partner_id.id or False,
                'partner_name': self.name or self.phone,
            },
        }

    def action_c2w_call_voip(self):
        self._c2w_require_phone()
        if not self.c2w_can_voip:
            raise UserError(_("Your user has no softphone extension set up."))
        return {
            'type': 'ir.actions.client',
            'tag': 'chat2work_contact.voip_dial',
            'params': {'number': self.phone, 'candidate_id': self.id},
        }

    def c2w_note_voip_call(self):
        """Called by the softphone action once it has actually dialled."""
        self.ensure_one()
        self.message_post(body=_("VoIP call attempted."))
        return True

    def action_c2w_open_message(self):
        self._c2w_require_phone()
        self._c2w_ensure_token()  # SMS templates can include the CV link
        return {
            'type': 'ir.actions.act_window',
            'name': _("Message %s", self.name or self.phone),
            'res_model': 'chat2work.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }


class WhatsAppCallPermissionChat2work(models.Model):
    _inherit = 'whatsapp.call.permission'

    def _c2w_candidates(self):
        self.ensure_one()
        return self.env['chat2work.candidate'].sudo().search([('phone', 'in', msisdn_variants('+' + self.phone))])

    def _display_person(self):
        return self._c2w_candidates()[:1].name or super()._display_person()

    def _post_note(self, body):
        super()._post_note(body)
        for candidate in self._c2w_candidates():
            candidate.message_post(body=body)

    def _after_reply(self):
        """Leave the agent a to-do, which outlasts the pop-up if they're offline."""
        super()._after_reply()
        if self.current_state != 'granted' or not self.requested_by_id:
            return
        for candidate in self._c2w_candidates():
            candidate.activity_schedule('mail.mail_activity_data_todo', user_id=self.requested_by_id.id,
                                        summary=_("Call on WhatsApp: permission given"))


class Chat2workCandidateErase(models.Model):
    _inherit = 'chat2work.candidate'

    def _c2w_erase_extra(self):
        super()._c2w_erase_extra()
        for rec in self:
            if rec.phone:
                self.env['whatsapp.call.permission'].sudo().search(
                    [('phone', 'in', [re.sub(r'\D', '', v) for v in msisdn_variants(rec.phone)])]).unlink()
