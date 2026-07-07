# -*- coding: utf-8 -*-
"""Channel registry.

A comm.channel row is metadata about a channel — its capabilities and which
Python adapter to load. Adapters are registered via the AdapterRegistry
(runtime/adapter_registry.py) at module load time; the DB row is the
data-driven side.
"""
from odoo import models, fields, api


class CommChannel(models.Model):
    _name = 'comm.channel'
    _description = 'Communication channel (registry)'
    _order = 'sequence, code'
    _rec_name = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True,
        help='Short identifier: whatsapp / sms / ussd / voice / email / etc.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    adapter_key = fields.Char(required=True,
        help='Registry key of the Python adapter class. Set by the channel '
             'adapter module (e.g. "whatsapp", "sms").')

    # Capability flags — the renderer consults these
    supports_buttons        = fields.Boolean(default=False)
    max_buttons             = fields.Integer(default=0)
    supports_lists          = fields.Boolean(default=False)
    max_list_rows           = fields.Integer(default=0)
    supports_media_image    = fields.Boolean(default=False)
    supports_media_video    = fields.Boolean(default=False)
    supports_media_audio    = fields.Boolean(default=False)
    supports_media_document = fields.Boolean(default=False)
    supports_typing         = fields.Boolean(default=False)
    supports_streaming      = fields.Boolean(default=False,
        help='Can push tokens as they arrive (voice TTS pipeline).')
    is_synchronous          = fields.Boolean(default=False,
        help='Response must be returned within the request window (USSD).')
    max_body_length         = fields.Integer(default=0,
        help='Hard char limit per outbound message. 0 = unlimited.')
    quiet_hours_start       = fields.Float(default=8.0,
        help='Default quiet-hours window start (local time, hours).')
    quiet_hours_end         = fields.Float(default=20.0)
    regulatory_lock         = fields.Boolean(default=False,
        help='Enforce quiet hours strictly (POPIA compliance).')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Channel code must be unique.'),
    ]

    @api.model
    def get_by_code(self, code):
        return self.search([('code', '=', code), ('active', '=', True)], limit=1)
