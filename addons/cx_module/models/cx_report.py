# -*- coding: utf-8 -*-
"""UCX reporting.

A genuinely-new analytics model (allowed per the reuse rule: new cx.* models
only for things that don't already exist). It's a read-only SQL view over the
reused Gen-2 runtime — one row per comm.conversation with denormalised
dimensions + measures — so the Reporting tab's pivot/graph views and the
Workspace dashboard all draw from the same ledger as the Inbox (no drift).
"""
from odoo import fields, models, tools


class CxReportConversation(models.Model):
    _name = 'cx.report.conversation'
    _description = 'UCX Conversation Analytics'
    _auto = False
    _order = 'opened_at desc'

    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    primary_channel_id = fields.Many2one('comm.channel', string='Channel', readonly=True)
    lifecycle_state = fields.Char(string='State', readonly=True)
    assigned_agent_id = fields.Many2one('res.users', string='Agent', readonly=True)
    bot_id = fields.Many2one('comm.bot', string='Bot', readonly=True)
    opened_at = fields.Datetime(string='Opened', readonly=True)
    conversation_count = fields.Integer(string='Conversations', readonly=True)
    interaction_count = fields.Integer(string='Messages', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW %s AS (
                SELECT
                    c.id                 AS id,
                    c.partner_id         AS partner_id,
                    c.primary_channel_id AS primary_channel_id,
                    c.lifecycle_state    AS lifecycle_state,
                    c.assigned_agent_id  AS assigned_agent_id,
                    c.bot_id             AS bot_id,
                    c.opened_at          AS opened_at,
                    1                    AS conversation_count,
                    (SELECT count(*) FROM comm_interaction i
                       WHERE i.conversation_id = c.id) AS interaction_count
                FROM comm_conversation c
            )
        """ % self._table)
