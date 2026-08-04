# -*- coding: utf-8 -*-

from odoo import fields, models


class CommDisposition(models.Model):
    """A configurable outcome / wrap-up code an agent sets on a contact.

    Deliberately channel-agnostic (not "call disposition") so the same
    taxonomy — "Resolved – billing", "Callback", "Spam" — can be applied
    to calls (whatsapp.call.log) and, later, to whole chat sessions
    (comm.conversation). Managed by Call Managers; set by any agent.
    """
    _name = "comm.disposition"
    _description = "Communication Disposition (outcome / wrap-up code)"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help="Short, stable code for reporting / integrations (optional).")
    category = fields.Selection(
        [
            ("resolved", "Resolved"),
            ("unresolved", "Unresolved"),
            ("callback", "Callback / Follow-up"),
            ("no_contact", "No contact"),
            ("invalid", "Invalid / Spam"),
            ("other", "Other"),
        ],
        default="other",
        help="Coarse bucket used to roll dispositions up in reporting.",
    )
    sequence = fields.Integer(default=10)
    color = fields.Integer(string="Color")
    active = fields.Boolean(default=True)
    note_required = fields.Boolean(
        string="Require note",
        help="When set, the agent should add a note when picking this "
             "disposition (e.g. a callback reason).",
    )
    description = fields.Char(help="Optional agent-facing hint shown in the picker.")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "The disposition code must be unique."),
    ]

    def name_get(self):
        result = []
        for rec in self:
            result.append((rec.id, rec.code and f"{rec.name} ({rec.code})" or rec.name))
        return result
