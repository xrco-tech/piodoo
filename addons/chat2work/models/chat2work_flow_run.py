# -*- coding: utf-8 -*-
"""How long each USSD or WhatsApp session took and how it ended.

A session is deleted when it ends, so this is what is left of it for the
dashboard: no name, number or answer, only the channel, the times and the
outcome. The candidate is linked where there is one, and the row stays (with
no link) if they are erased."""

from odoo import fields, models

CHANNELS = [('ussd', 'USSD'), ('whatsapp', 'WhatsApp')]
OUTCOMES = [
    ('signup', 'Signed up'),
    ('update', 'Updated their status'),
    ('callback', 'Asked for a callback'),
    ('other', 'Ended another way'),
    ('abandoned', 'Left before the end'),
]


class Chat2workFlowRun(models.Model):
    _name = 'chat2work.flow.run'
    _description = 'Chat2Work Session Time'
    _order = 'started_at desc, id desc'
    _rec_name = 'started_at'

    channel = fields.Selection(CHANNELS, required=True, readonly=True, index=True)
    outcome = fields.Selection(OUTCOMES, required=True, readonly=True)
    started_at = fields.Datetime('Started', required=True, readonly=True, index=True)
    seconds = fields.Integer('Seconds, First to Last Message', readonly=True)
    turns = fields.Integer('Replies', readonly=True, help="How many times the person answered.")
    candidate_id = fields.Many2one('chat2work.candidate', ondelete='set null', readonly=True)
