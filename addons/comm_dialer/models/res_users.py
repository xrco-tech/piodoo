# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # The agent's Asterisk WebRTC endpoint. The dialer bridges answered calls to
    # PJSIP/<dialer_sip_ext>. Provisioned per agent (matches a pjsip.conf endpoint).
    dialer_sip_ext = fields.Char(
        'Dialer SIP Extension',
        help="PJSIP endpoint name for this agent's WebRTC softphone (e.g. 1001). "
             "The dialer bridges answered calls to PJSIP/<ext>.")
    dialer_sip_secret = fields.Char(
        'Dialer SIP Secret',
        help="Password the agent's browser softphone registers with (used when "
             "provisioning the matching Asterisk endpoint).")
    dialer_manual_answer = fields.Boolean(
        'Manual Answer',
        help="Ring incoming dialer calls with Accept/Decline instead of "
             "auto-answering. Auto-answer is standard for progressive/predictive "
             "(the customer is already on the line); manual suits preview / "
             "low-volume work or agents who want a moment before connecting.")
