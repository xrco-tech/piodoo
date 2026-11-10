# -*- coding: utf-8 -*-
"""Hooks for inbound (MO) SMS, shared by every provider's webhook.

`_comm_partner_for_number` finds the existing contact for a sender however
their number was typed in (+27 82 …, 27820…, 082…). `_comm_record_inbound` is
called for every inbound SMS before any chatbot routing; it does nothing here
and is extended by the inbox modules (comm_chatbot_sms) to keep the message.
"""

import re

from odoo import api, models


def sa_local(digits):
    """'27821234567' → '0821234567' (South African numbers only)."""
    if digits.startswith('27') and len(digits) == 11:
        return '0' + digits[2:]
    return None


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    @api.model
    def _comm_partner_for_number(self, number):
        """The oldest contact with this mobile/phone number, never a company's
        own contact (the company may share the number it sends from)."""
        Partner = self.env['res.partner'].sudo()
        digits = re.sub(r'\D', '', number or '')
        if not digits:
            return Partner.browse()
        if digits.startswith('0') and len(digits) == 10:
            digits = '27' + digits[1:]          # local SA format → international
        company_partners = self.env['res.company'].sudo().search([]).partner_id.ids
        for query in ('+' + digits, digits, sa_local(digits)):
            if not query:
                continue
            partner = Partner.search([
                ('phone_mobile_search', '=', query), ('id', 'not in', company_partners),
            ], order='id', limit=1)
            if partner:
                return partner
        return Partner.browse()

    @api.model
    def _comm_record_inbound(self, partner, number, body, provider_message_id=None, to_number=None):
        """Called once per inbound SMS. Extended to keep it somewhere useful."""
        return False
