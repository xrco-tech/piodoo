# -*- coding: utf-8 -*-
"""Call team — a named queue of agents.

Routing rules point at teams, not users. Teams solve two problems the
old rule.agent_ids + rule.agent_group_id union created:

  1. A user's team membership was scattered across N rules; adding a
     new hire required editing every rule. Now the hire joins the team
     and picks up its rules for free.
  2. Rule ownership was fuzzy — was "Support VIP" a rule or a group?
     Teams answer that clearly: rules describe when to route, teams
     describe who is on the receiving end.
"""

from odoo import fields, models


class WhatsappCallTeam(models.Model):
    _name = "whatsapp.call.team"
    _description = "WhatsApp Call Team"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(help="What is this team for? Shown as a "
                                   "hint on the routing rule form.")
    color = fields.Integer(default=0,
        help="Kanban colour tag. Purely cosmetic.")

    # Optional: bind the team to a WABA. Not a routing constraint — it's
    # a UX hint so admins can quickly see which team owns which number.
    account_id = fields.Many2one(
        "comm.whatsapp.account", string="Primary WABA", ondelete="set null",
    )

    member_ids = fields.Many2many(
        "res.users", "wa_call_team_member_rel",
        "team_id", "user_id",
        string="Members",
        help="Users on this team. Their browsers ring when a call is "
             "routed here, provided they're marked Available.",
    )
    member_count = fields.Integer(
        string="Members", compute="_compute_member_count", store=False,
    )
    rule_ids = fields.Many2many(
        "whatsapp.call.routing.rule",
        "wa_call_route_team_rel",  # matches the FK on rule side
        "team_id", "rule_id",
        string="Routing Rules",
        readonly=True,
    )
    rule_count = fields.Integer(
        string="Rules", compute="_compute_rule_count", store=False,
    )

    _sql_constraints = [
        ("name_unique", "UNIQUE(name)",
         "Team names must be unique."),
    ]

    def _compute_member_count(self):
        for t in self:
            t.member_count = len(t.member_ids)

    def _compute_rule_count(self):
        for t in self:
            t.rule_count = len(t.rule_ids)

    def action_view_rules(self):
        self.ensure_one()
        return {
            "type":      "ir.actions.act_window",
            "name":      f"Rules — {self.name}",
            "res_model": "whatsapp.call.routing.rule",
            "view_mode": "list,form",
            "domain":    [("team_ids", "in", [self.id])],
            "context":   {"default_team_ids": [(6, 0, [self.id])]},
        }
