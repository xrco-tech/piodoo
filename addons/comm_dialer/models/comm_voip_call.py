# -*- coding: utf-8 -*-
from odoo import fields, models


class CommVoipCall(models.Model):
    _inherit = 'comm.voip.call'

    # Back-link so a call originated by the dialer knows its call-list row.
    dialer_contact_id = fields.Many2one(
        'comm.dialer.contact', 'Dialer Contact',
        ondelete='set null', index=True)
    # Progressive pre-assigns a specific agent at dial time; predictive leaves
    # this empty and the bridge service binds a Ready agent on answer.
    dialer_agent_session_id = fields.Many2one(
        'comm.dialer.agent.session', 'Assigned Agent', ondelete='set null')
    # Convenience reads for the ARI bridge service (via search_read).
    agent_sip_ext = fields.Char(related='dialer_agent_session_id.sip_ext')
    dialer_campaign_id = fields.Many2one(
        related='dialer_contact_id.campaign_id', store=True,
        string='Dialer Campaign', index=True)
