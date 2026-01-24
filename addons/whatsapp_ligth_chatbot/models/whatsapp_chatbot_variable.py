# -*- coding: utf-8 -*-

import logging
import json
import ast
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from datetime import datetime

_logger = logging.getLogger(__name__)


def convert_text_to_date(text_date):
    """Convert text date to date object"""
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(text_date, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Could not parse date from: {text_date}")


class WhatsAppChatbotVariable(models.Model):
    _name = 'whatsapp.chatbot.variable'
    _description = 'WhatsApp Chatbot Variable'
    _order = 'name asc'

    name = fields.Char(string="Variable", tracking=True, required=True)
    data_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
        ('json', 'JSON'),
        ('document', 'Document'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
    ], string="Type", required=True, default='text')
    chatbot_id = fields.Many2one("whatsapp.chatbot", string="Chatbot", required=True, tracking=True, ondelete='cascade')


class WhatsAppChatbotVariableValue(models.Model):
    _name = 'whatsapp.chatbot.value'
    _description = 'WhatsApp Chatbot Value'
    _order = 'value asc'

    value = fields.Char(string="Value", tracking=True)
    contact_id = fields.Many2one("whatsapp.chatbot.contact", string="Contact", required=True, tracking=True, ondelete='cascade')
    variable_id = fields.Many2one("whatsapp.chatbot.variable", string="Variable", required=True, tracking=True, ondelete='cascade')
    variable_type = fields.Selection(related="variable_id.data_type", string="Variable Type", tracking=True, store=True)
    chatbot_id = fields.Many2one("whatsapp.chatbot", related="variable_id.chatbot_id", string="Chatbot", tracking=True, store=True)

    value_text = fields.Char(string="Text Value", compute="_compute_value_text", store=True)
    value_integer = fields.Integer(string="Integer Value", compute="_compute_value_integer", store=True)
    value_float = fields.Float(string="Float Value", compute="_compute_value_float", store=True)
    value_date = fields.Date(string="Date Value", compute="_compute_value_date", store=True)
    value_boolean = fields.Boolean(string="Boolean Value", compute="_compute_value_boolean", store=True)
    value_json = fields.Json(string="JSON Value", compute="_compute_value_json", store=True)
    value_file = fields.Many2one("ir.attachment", string="File Value", tracking=True)

    @api.depends('variable_type', 'value')
    def _compute_value_text(self):
        for rec in self:
            if rec.variable_type == "text":
                rec.value_text = str(rec.value) if rec.value else False
            else:
                rec.value_text = False
    
    @api.depends('variable_type', 'value')
    def _compute_value_integer(self):
        for rec in self:
            if rec.variable_type == "integer":
                try:
                    rec.value_integer = int(rec.value) if rec.value else False
                except:
                    rec.value_integer = False
            else:
                rec.value_integer = False

    @api.depends('variable_type', 'value')
    def _compute_value_float(self):
        for rec in self:
            if rec.variable_type == "float":
                try:
                    rec.value_float = float(rec.value) if rec.value else False
                except:
                    rec.value_float = False
            else:
                rec.value_float = False

    @api.depends('variable_type', 'value')
    def _compute_value_date(self):
        for rec in self:
            if rec.variable_type == "date":
                try:
                    rec.value_date = convert_text_to_date(rec.value) if rec.value else False
                except:
                    rec.value_date = False
            else:
                rec.value_date = False

    @api.depends('variable_type', 'value')
    def _compute_value_boolean(self):
        for rec in self:
            if rec.variable_type == "boolean":
                try:
                    rec.value_boolean = bool(rec.value) if rec.value else False
                except:
                    rec.value_boolean = False
            else:
                rec.value_boolean = False
    
    @api.depends('variable_type', 'value')
    def _compute_value_json(self):
        for rec in self:
            if rec.variable_type == "json" and rec.value:
                try:
                    python_dict = ast.literal_eval(rec.value)
                    json_str = json.dumps(python_dict, indent=2)
                    rec.value_json = json.loads(json_str)
                except Exception as e:
                    rec.value_json = False
                    _logger.error(f"Invalid value for JSON variable {e}")
            else:
                rec.value_json = False


class WhatsAppChatbotVariableTrigger(models.Model):
    _name = 'whatsapp.chatbot.variable.trigger'
    _description = 'WhatsApp Chatbot Variable Trigger'

    display_name = fields.Char(compute="_compute_display_name", store=True)
    value = fields.Char(string="Value", tracking=True)
    step_id = fields.Many2one("whatsapp.chatbot.step", string="Chatbot Step", required=True, tracking=True, ondelete='cascade')
    trigger_step_id = fields.Many2one("whatsapp.chatbot.step", related="step_id.parent_id", string="Trigger Step", required=True, tracking=True)
    chatbot_id = fields.Many2one("whatsapp.chatbot", related="step_id.chatbot_id", string="Chatbot", required=True, tracking=True)
    variable_id = fields.Many2one("whatsapp.chatbot.variable", string="Variable", required=True, tracking=True, ondelete='cascade')
    sequence = fields.Integer(string="Sequence", tracking=True, default=10)
    variable_data_type = fields.Selection(related="variable_id.data_type", string="Variable Data Type", required=True)
    operator = fields.Selection([
        ('is_equal_to', 'Is Equal To'),
        ('is_not_equal_to', 'Is Not Equal To'),
        ('contains', 'Contains'),
        ('does_not_contain', 'Does Not Contain'),
        ('less_than', 'Less Than'),
        ('greater_than', 'Greater Than'),
    ], string="Operator", required=True, default='is_equal_to')

    @api.depends('variable_id.name', 'operator', 'value')
    def _compute_display_name(self):
        operator_labels = dict(self._fields['operator'].selection)
        for record in self:
            var_name = record.variable_id.name or ""
            op_label = operator_labels.get(record.operator, "")
            if record.operator in ['is_set', 'is_not_set']:
                record.display_name = f"{var_name} {op_label}"
            else:
                record.display_name = f"{var_name} {op_label} {record.value or ''}"

