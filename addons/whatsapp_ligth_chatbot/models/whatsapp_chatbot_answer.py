# -*- coding: utf-8 -*-

import logging
from odoo import api, models, fields

_logger = logging.getLogger(__name__)


class WhatsAppChatbotAnswer(models.Model):
    _name = 'whatsapp.chatbot.answer'
    _description = 'WhatsApp Chatbot Answer'
    _rec_name = 'value'

    display_name = fields.Char(compute="_compute_display_name", store=True)
    value = fields.Char(string="Value", tracking=True, required=True)
    step_id = fields.Many2one(
        "whatsapp.chatbot.step",
        string="Chatbot Step",
        required=True,
        tracking=True,
        ondelete='cascade',
        default=lambda self: self.env.context.get('default_step_id'),
    )
    trigger_step_id = fields.Many2one("whatsapp.chatbot.step", related="step_id.parent_id", string="Trigger Step", required=True, tracking=True)
    chatbot_id = fields.Many2one("whatsapp.chatbot", related="step_id.chatbot_id", string="Chatbot", required=True, tracking=True)
    sequence = fields.Integer(string="Sequence", tracking=True, default=10)
    answer_data_type = fields.Selection(related="trigger_step_id.answer_data_type", string="Answer Data Type", required=True)
    operator = fields.Selection([
        ('is_equal_to', 'Is Equal To'),
        ('is_not_equal_to', 'Is Not Equal To'),
        ('contains', 'Contains'),
        ('does_not_contain', 'Does Not Contain'),
        ('less_than', 'Less Than'),
        ('greater_than', 'Greater Than'),
    ], string="Operator", required=True, default='is_equal_to')

    @api.depends('trigger_step_id.name', 'operator', 'value')
    def _compute_display_name(self):
        operator_labels = dict(self._fields['operator'].selection)
        for record in self:
            var_name = record.trigger_step_id.name or ""
            op_label = operator_labels.get(record.operator, "")
            if record.operator in ['is_set', 'is_not_set']:
                record.display_name = f"{var_name} {op_label}"
            else:
                record.display_name = f"{var_name} {op_label} {record.value or ''}"

