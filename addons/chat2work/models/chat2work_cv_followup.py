# -*- coding: utf-8 -*-
"""What happens once a CV is in, and CVs sent straight to the WhatsApp number.

"What happens next": once the candidate has a finished CV (built or checked on
the CV page, or an upload only an agent can type up), they're told once that
we're reviewing it. By WhatsApp inside the 24-hour window, else by the approved
template, else by SMS.

People also send their CV to the WhatsApp number instead of using the link. A
PDF, Word document or photo from a candidate is saved as their CV upload, just
like one from the CV page. Photos of a multi-page CV arrive one by one, so
photos within a few minutes of the first are kept as extra pages.
"""

import logging
import re
from datetime import timedelta

from odoo import api, fields, models

from .chat2work import _send_sms
from .chat2work_ussd import first_name, msisdn_variants, normalize_msisdn

_logger = logging.getLogger(__name__)

NEXT_STEPS_TEMPLATE = 'chat2work_cv_received'
CV_MIMETYPES = {
    'application/pdf': '.pdf',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/heic': '.heic',
}
MAX_CV_BYTES = 5 * 1024 * 1024
PHOTO_PAGES_WINDOW = timedelta(minutes=10)


class Chat2workCandidateFollowup(models.Model):
    _inherit = 'chat2work.candidate'

    cv_next_steps_sent_at = fields.Datetime('"What Happens Next" Sent', copy=False, readonly=True)

    def _c2w_next_steps_whatsapp_text(self):
        name = first_name(self.name)
        return ("Thanks%s, your CV is in ✅ Our team is reviewing it to match you with suitable opportunities. "
                "We'll contact you here or by SMS when something fits. This can take a while, so keep your "
                "phone on. Chat2Work never asks for money." % (' ' + name if name else ''))

    def _c2w_next_steps_sms_text(self):
        return ("Chat2Work: thanks, your CV is in. We're reviewing it to match you with suitable work and "
                "will contact you when something fits. We never ask for money.")

    def _c2w_next_steps_by_whatsapp(self):
        """A normal message inside the 24-hour window, else the approved template.
        Returns True when Meta accepted it."""
        self.ensure_one()
        Message = self.env['whatsapp.message'].sudo()
        text = self._c2w_next_steps_whatsapp_text()
        if self._c2w_wa_window_open():
            res = Message.send_whatsapp_payload(self.phone, {'type': 'text', 'text': {'body': text}},
                                                log_body=text, log_type='text')
        else:
            template = self.env['whatsapp.template'].sudo().search(
                [('name', '=', NEXT_STEPS_TEMPLATE), ('status', '=', 'APPROVED')], limit=1)
            if not template:
                return False
            res = Message.send_whatsapp_payload(self.phone, {
                'type': 'template',
                'template': {
                    'name': template.name,
                    'language': {'code': template.language},
                    'components': [{'type': 'body', 'parameters': [
                        {'type': 'text', 'text': first_name(self.name) or 'there'}]}],
                },
            }, account=template.account_id or None, log_body=text, log_type='template')
        self._c2w_log_event('whatsapp', 'outbound', text, None if res.get('success') else 'failed',
                            res.get('message_id'))
        return bool(res.get('success'))

    def _c2w_send_next_steps(self):
        """Tell them once that their CV is being reviewed. Never stops the caller."""
        for rec in self.sudo().filtered(lambda r: not r.cv_next_steps_sent_at and r.phone):
            try:
                if not (rec.whatsapp_opt_in and rec._c2w_next_steps_by_whatsapp()):
                    text = rec._c2w_next_steps_sms_text()
                    sent = _send_sms(rec.env, rec.phone, text)
                    rec._c2w_log_event('sms', 'outbound', text, 'sent' if sent else 'failed')
                rec.cv_next_steps_sent_at = fields.Datetime.now()
            except Exception:  # noqa: BLE001 - a failed notice mustn't lose the CV
                _logger.exception("chat2work: 'what happens next' for candidate %s failed", rec.id)

    def write(self, vals):
        res = super().write(vals)
        if vals.get('cv_state') == 'built' or vals.get('cv_rebuild_state') == 'needs_agent':
            self._c2w_send_next_steps()
        return res


class Chat2workWaSessionCv(models.Model):
    _inherit = 'chat2work.wa.session'

    @api.model
    def _reply_text(self, wa_id, account, text):
        self.env['whatsapp.message'].sudo().send_whatsapp_payload(
            wa_id, {'type': 'text', 'text': {'body': text}}, account=account or None,
            log_body=text, log_type='text')

    @api.model
    def wa_take_cv(self, wa_message, value_data):
        """Save a CV document or photo sent to the number. Returns True if Chat2Work took it."""
        self = self.sudo()
        phone_number_id = ((value_data or {}).get('metadata') or {}).get('phone_number_id')
        account = self.env['comm.whatsapp.account'].sudo().find_for_phone_number_id(phone_number_id)
        if not self._account_allowed(account):
            return False
        att = wa_message.media_attachment_id.sudo()
        mimetype = (att.mimetype or '').split(';')[0].strip().lower()
        if wa_message.message_type not in ('document', 'image') or (att and mimetype not in CV_MIMETYPES):
            return False
        photo = wa_message.message_type == 'image'
        wa_id = re.sub(r'\D', '', wa_message.wa_id or '')
        candidate = self.env['chat2work.candidate'].sudo().search(
            [('phone', 'in', msisdn_variants(normalize_msisdn(wa_id)))], limit=1)
        if not candidate:
            if photo:
                return False  # a photo from a stranger is a conversation for an agent
            if self.search_count([('wa_id', '=', wa_id)]):
                text = "Thanks! Please answer the question above first. You can send your CV once your profile is created."
            else:
                text = ('Thanks! To send us your CV, first create your free Chat2Work profile: send "Ispani". '
                        'Then send your CV here.')
            self._reply_text(wa_id, account, text)
            return True
        if not att:
            self._reply_text(wa_id, account, "Sorry, we couldn't open that file. Please send it again, or use "
                                             "the CV link we sent you.")
            return True
        if (att.file_size or 0) > MAX_CV_BYTES:
            self._reply_text(wa_id, account, "That file is bigger than 5 MB. Please send a smaller file, or a "
                                             "photo of each page.")
            return True
        current = candidate.cv_attachment_id.sudo()
        if (photo and candidate.cv_state == 'uploaded' and (current.mimetype or '').startswith('image/')
                and candidate.cv_submitted_at
                and candidate.cv_submitted_at >= fields.Datetime.now() - PHOTO_PAGES_WINDOW):
            att.copy({'res_model': candidate._name, 'res_id': candidate.id,
                      'name': 'CV page (WhatsApp)%s' % CV_MIMETYPES[mimetype]})
            candidate.message_post(body="Another CV page received on WhatsApp.")
            candidate._c2w_log_event('whatsapp', 'inbound', 'Sent another CV page (photo).')
            return True
        name = att.name if not photo and att.name else 'CV upload (WhatsApp)%s' % CV_MIMETYPES[mimetype]
        candidate.with_context(c2w_cv_source='whatsapp')._c2w_store_cv_file(name, att.raw, mimetype, 'uploaded')
        if photo:
            # An agent types photos up; this message already says what happens next.
            text = ("Thanks, we've got your CV ✅ If it has more pages, send a photo of each one now. Our team "
                    "will type it up and review it to match you with suitable opportunities. We'll contact you "
                    "here or by SMS. Chat2Work never asks for money.")
            candidate.cv_next_steps_sent_at = fields.Datetime.now()
        else:
            text = ("Thanks, we've got your CV ✅ We'll put it into our standard format and send you a link to "
                    "check it in a few minutes.")
        self._reply_text(wa_id, account, text)
        return True
