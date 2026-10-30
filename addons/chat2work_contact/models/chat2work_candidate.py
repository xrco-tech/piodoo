# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class Chat2workCandidateContact(models.Model):
    _inherit = 'chat2work.candidate'

    c2w_can_voip = fields.Boolean(compute='_compute_c2w_can_voip')

    def _compute_c2w_can_voip(self):
        can = bool(self.env.user.sudo().dialer_sip_ext)
        for rec in self:
            rec.c2w_can_voip = can

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
