# -*- coding: utf-8 -*-
"""Transient state for a single USSD session.

USSD is synchronous: the carrier calls our endpoint once per keypress with
the full breadcrumb of inputs in the `text` field. We could in principle
re-walk the tree from scratch every turn, but for any non-trivial flow
that's wasteful (each set_variable / execute_code side-effect would
re-run). So we store the session's current step + variables / call_stack
keyed by the carrier's session_id.

Sessions are cleaned up when the flow ends, when the notifications
endpoint reports completion/timeout/hangup, or by a janitor that purges
rows older than the carrier's session ceiling (typically 60s).
"""

from odoo import api, fields, models


class WhatsAppChatbotUssdSession(models.Model):
    _name = 'whatsapp.chatbot.ussd.session'
    _description = 'WhatsApp Chatbot USSD Session'
    _order = 'create_date desc'

    session_id = fields.Char(string="Session ID", required=True, index='btree')
    service_code = fields.Char(string="Service Code", index='btree')
    phone_number = fields.Char(string="Phone Number", index='btree')
    chatbot_id = fields.Many2one(
        "whatsapp.chatbot", string="Chatbot", required=True, ondelete='cascade',
    )
    contact_id = fields.Many2one(
        "whatsapp.chatbot.contact", string="Contact", ondelete='set null',
    )
    current_step_id = fields.Many2one(
        "whatsapp.chatbot.step", string="Current Step", ondelete='set null',
        help="The step the session is currently waiting on user input for.",
    )
    # JSON snapshots — mirror the per-contact state but scoped to this session
    # so a contact can have parallel USSD activity without state collisions.
    variables = fields.Json(string="Variables Snapshot", default=dict)
    call_stack = fields.Json(string="Call Stack", default=list)
    breadcrumb = fields.Char(
        string="Input Breadcrumb",
        help="The carrier's accumulated `text` field; useful for debugging.",
    )
    outcome = fields.Selection([
        ('open', 'Open'),
        ('completed', 'Completed'),
        ('timeout', 'Timeout'),
        ('hangup', 'User Hangup'),
        ('error', 'Error'),
    ], string="Outcome", default='open', tracking=False)
    last_response = fields.Text(
        string="Last Response",
        help="The most recent CON/END body returned to the carrier — useful for debugging.",
    )

    _sql_constraints = [
        (
            'session_id_unique',
            'UNIQUE(session_id)',
            "A USSD session row already exists with this session_id.",
        ),
    ]

    @api.model
    def find_or_create_for_inbound(self, session_id, service_code, phone_number, chatbot, contact):
        """Idempotent session lookup. Returns the existing session if any,
        otherwise creates a fresh one bound to the resolved chatbot."""
        existing = self.search([('session_id', '=', session_id)], limit=1)
        if existing:
            return existing
        return self.create({
            'session_id': session_id,
            'service_code': service_code or False,
            'phone_number': phone_number or False,
            'chatbot_id': chatbot.id,
            'contact_id': contact.id if contact else False,
        })
