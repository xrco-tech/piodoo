# -*- coding: utf-8 -*-
"""Inbound call routing rules.

A ringing call is matched against these rules in order. The first
matching rule's target agent set (intersected with users currently
Available) receives the popup. If no rule matches, we fall back to
broadcasting to every available user — preserving the pre-routing
behaviour so an install with zero rules keeps working as before.
"""

import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WhatsappCallRoutingRule(models.Model):
    _name = "whatsapp.call.routing.rule"
    _description = "WhatsApp Inbound Call Routing Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # ── Match ──────────────────────────────────────────────────────
    # Optional: leave empty to match calls on any WABA.
    account_id = fields.Many2one(
        "comm.whatsapp.account", string="WABA Account",
        ondelete="cascade",
        help="Only match calls landing on this WABA. Empty = any WABA.",
    )
    caller_pattern = fields.Char(
        string="Caller Number Pattern",
        help="Optional regex applied to the caller's from_number. "
             "Empty = match any caller. Examples:\n"
             "  ^\\+27      — any South African number\n"
             "  ^\\+1(555)  — a specific US area code\n"
             "  ^0821234567$ — an exact match",
    )

    # ── Route target ──────────────────────────────────────────────
    team_ids = fields.Many2many(
        "whatsapp.call.team", "wa_call_route_team_rel",
        "rule_id", "team_id",
        string="Teams",
        help="Every member of these teams is a candidate. Only members "
             "currently marked Available in the systray get the ringing "
             "popup.",
    )

    match_count = fields.Integer(
        string="Matched", compute="_compute_match_count",
        help="How many calls this rule has actually routed. Reset on "
             "rule edit — advisory only.",
    )

    _sql_constraints = [
        ("sequence_positive",
         "CHECK(sequence >= 0)",
         "Sequence must be non-negative."),
    ]

    def _compute_match_count(self):
        # Placeholder — a real counter would need per-rule audit trail.
        # Kept for future extension.
        for r in self:
            r.match_count = 0

    def _regex(self):
        """Return a compiled regex or None. Bad regexes disable the
        pattern check rather than crashing the routing loop."""
        self.ensure_one()
        if not self.caller_pattern:
            return None
        try:
            return re.compile(self.caller_pattern)
        except re.error as e:
            _logger.warning(
                "comm_whatsapp_calling: rule %s has invalid regex %r: %s",
                self.name, self.caller_pattern, e,
            )
            return None

    def _matches(self, account_id, from_number):
        """Cheap check: WABA scope + optional regex on the caller."""
        self.ensure_one()
        if self.account_id and self.account_id.id != account_id:
            return False
        rx = self._regex()
        if rx is not None and not rx.search(from_number or ""):
            return False
        return True

    def _resolve_users(self):
        """Union of every member of every attached team."""
        self.ensure_one()
        return self.mapped("team_ids.member_ids")

    @api.model
    def resolve_target_users(self, account_id, from_number):
        """Public API used by the webhook. Walks active rules in
        sequence order; the first that matches wins. Returns the set
        of res.users records whose browsers should ring, filtered to
        only those currently Available. When no rule matches or the
        matching rule resolves to zero available users, returns the
        empty set — the caller decides whether to fall back to all-
        available broadcast."""
        rules = self.sudo().search([("active", "=", True)])
        for rule in rules:
            if not rule._matches(account_id, from_number):
                continue
            targets = rule._resolve_users()
            available = targets.filtered(
                lambda u: u.active and u.wa_call_presence == "available"
            )
            _logger.info(
                "comm_whatsapp_calling: routing rule %s matched — "
                "%s targets, %s available",
                rule.name, len(targets), len(available),
            )
            return available
        return self.env["res.users"]
