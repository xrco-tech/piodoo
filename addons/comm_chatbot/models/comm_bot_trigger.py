# -*- coding: utf-8 -*-
from odoo import models, fields, api


TRIGGER_KIND_SELECTION = [
    ('keyword',         'Keyword'),
    ('service_code',    'Service code (USSD)'),
    ('inbound_call',    'Inbound call'),
    ('template_reply',  'Template reply (WA campaign follow-through)'),
    ('scheduled',       'Scheduled (cron / campaign)'),
    ('api',             'API call'),
    ('any_inbound',     'Any inbound message (fallback)'),
]


class CommBotTrigger(models.Model):
    _name = 'comm.bot.trigger'
    _description = 'How a bot starts'
    _order = 'bot_id, priority, id'

    bot_id = fields.Many2one('comm.bot', required=True, ondelete='cascade',
                             index=True)
    channel_id = fields.Many2one('comm.channel', required=True, index=True)
    kind = fields.Selection(TRIGGER_KIND_SELECTION, required=True, default='keyword',
                            index=True)
    value = fields.Char(
        help='Depends on kind: keyword text, USSD code, template name, etc.')
    priority = fields.Integer(default=10,
        help='Lower = higher priority when multiple triggers match.')
    match_mode = fields.Selection([
        ('exact',    'Exact match'),
        ('prefix',   'Prefix'),
        ('contains', 'Contains'),
        ('regex',    'Regex'),
    ], default='exact')
    case_sensitive = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    @api.model
    def find_trigger(self, channel_code, body, kind=None):
        """Match an inbound message to a trigger. Returns comm.bot.trigger or empty."""
        channel = self.env['comm.channel'].get_by_code(channel_code)
        if not channel:
            return self.browse()
        domain = [
            ('channel_id', '=', channel.id),
            ('active', '=', True),
            ('bot_id.active', '=', True),
            ('bot_id.engine_mode', 'in', ('live', 'shadow')),
        ]
        if kind:
            domain.append(('kind', '=', kind))
        candidates = self.search(domain, order='priority, id')
        for trg in candidates:
            if trg._matches(body):
                return trg
        return self.browse()

    def _matches(self, body):
        self.ensure_one()
        if not self.value:
            return self.kind == 'any_inbound'
        haystack = (body or '') if self.case_sensitive else (body or '').lower()
        needle = self.value if self.case_sensitive else self.value.lower()
        if self.match_mode == 'exact':
            return haystack.strip() == needle
        if self.match_mode == 'prefix':
            return haystack.startswith(needle)
        if self.match_mode == 'contains':
            return needle in haystack
        if self.match_mode == 'regex':
            import re
            try:
                return bool(re.search(self.value, body or '',
                                      0 if self.case_sensitive else re.IGNORECASE))
            except re.error:
                return False
        return False
