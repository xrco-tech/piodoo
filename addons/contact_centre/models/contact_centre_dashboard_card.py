# -*- coding: utf-8 -*-

from odoo import fields, models


class ContactCentreDashboardCard(models.Model):
    _name = "contact.centre.dashboard.card"
    _description = "Contact Centre Dashboard Custom Card"
    _order = "sequence asc, id asc"

    name = fields.Char("Label", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    # Selection, not free text: makes it impossible for a card (however it
    # was created - by hand or via the AI Copilot chat) to point at an
    # arbitrary/sensitive model. Same models the dashboard's own hardcoded
    # cards already query.
    model_name = fields.Selection([
        ("contact.centre.contact", "Contacts"),
        ("contact.centre.message", "Messages"),
        ("contact.centre.campaign", "Campaigns"),
        ("whatsapp.chatbot", "Chatbots"),
        ("contact.centre.chatbot.session", "Chatbot Sessions"),
        ("whatsapp.call.log", "WhatsApp Calls"),
    ], required=True)

    metric_type = fields.Selection([
        ("count", "Record Count"),
        ("group_by", "Breakdown by Field"),
    ], required=True, default="count")

    # A real list of lists (never an eval'd string) - no code-execution
    # surface. Invalid domains just fail that one card's fetch client-side.
    domain = fields.Json(default=list)
    group_by_field = fields.Char(help="Only used when Metric Type is 'Breakdown by Field'")

    icon = fields.Char(default="fa-bar-chart")
    color = fields.Selection([
        ("primary", "Primary"),
        ("info", "Info"),
        ("warning", "Warning"),
        ("success", "Success"),
        ("danger", "Danger"),
    ], default="primary")
