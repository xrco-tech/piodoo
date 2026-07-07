# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


VARIABLE_TYPE_SELECTION = [
    ('string',      'String'),
    ('int',         'Integer'),
    ('float',       'Float'),
    ('bool',        'Boolean'),
    ('date',        'Date'),
    ('datetime',    'Datetime'),
    ('json',        'JSON'),
    ('list',        'List'),
    ('contact_ref', 'Contact reference'),
]


class CommBotVariable(models.Model):
    _name = 'comm.bot.variable'
    _description = 'Declared variable on a bot'
    _order = 'bot_id, name'

    bot_id = fields.Many2one('comm.bot', required=True, ondelete='cascade',
                             index=True)
    name = fields.Char(required=True,
        help='Reference as {{state.<name>}} in bodies and prompts.')
    type = fields.Selection(VARIABLE_TYPE_SELECTION, required=True,
                            default='string')
    default_value = fields.Char(
        help='Initial value when a new conversation starts.')
    is_persistent = fields.Boolean(
        help='If True, value carries over to future conversations for the '
             'same partner (stored on res.partner.chatbot_state).')
    description = fields.Char()

    @api.constrains('bot_id', 'name')
    def _check_unique_name(self):
        for var in self:
            if not var.name.replace('_', '').isalnum():
                raise ValidationError(
                    f'Variable name "{var.name}" must be alphanumeric with underscores.')
            dupes = self.search([
                ('bot_id', '=', var.bot_id.id),
                ('name', '=', var.name),
                ('id', '!=', var.id),
            ])
            if dupes:
                raise ValidationError(
                    f'Variable "{var.name}" already declared on bot {var.bot_id.name}.')
