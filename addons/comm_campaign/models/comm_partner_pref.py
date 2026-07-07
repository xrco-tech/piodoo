# -*- coding: utf-8 -*-
from odoo import models, fields, api


PURPOSE_SELECTION = [
    ('marketing',      'Marketing'),
    ('transactional',  'Transactional'),
    ('service',        'Service'),
    ('authentication', 'Authentication'),
]


class CommPartnerCommunicationPreference(models.Model):
    _name = 'comm.partner.communication.preference'
    _description = 'Per-partner, per-channel, per-purpose communication consent'
    _order = 'partner_id, channel_id, purpose'

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade',
                                 index=True)
    channel_id = fields.Many2one('comm.channel', required=True, index=True)
    purpose = fields.Selection(PURPOSE_SELECTION, required=True, default='marketing')
    opted_in = fields.Boolean(default=True)
    opted_in_at = fields.Datetime(default=fields.Datetime.now)
    opt_out_reason = fields.Char()
    opt_out_source = fields.Selection([
        ('keyword',  'Keyword (STOP/END/...)'),
        ('manual',   'Manual (agent)'),
        ('link',     'Unsubscribe link'),
        ('bounce',   'Delivery failure'),
    ])

    _sql_constraints = [
        ('partner_channel_purpose_uniq',
         'unique(partner_id, channel_id, purpose)',
         'Only one preference per (partner, channel, purpose).'),
    ]

    @api.model
    def is_opted_in(self, partner, channel, purpose='marketing'):
        # Authentication and transactional messages bypass opt-out
        if purpose in ('authentication', 'transactional'):
            return True
        if partner.marketing_opt_out:
            return False
        pref = self.search([
            ('partner_id', '=', partner.id),
            ('channel_id', '=', channel.id),
            ('purpose', '=', purpose),
        ], limit=1)
        if pref:
            return pref.opted_in
        # No preference row → default opt-in (POPIA requires explicit consent
        # at partner creation; enforcement is on the acquisition side, not here)
        return True

    @api.model
    def opt_out(self, partner, channel, purpose='marketing',
                reason=None, source='manual'):
        existing = self.search([
            ('partner_id', '=', partner.id),
            ('channel_id', '=', channel.id),
            ('purpose', '=', purpose),
        ], limit=1)
        vals = {
            'opted_in': False,
            'opt_out_reason': reason,
            'opt_out_source': source,
        }
        if existing:
            existing.write(vals)
            return existing
        vals.update({'partner_id': partner.id, 'channel_id': channel.id,
                     'purpose': purpose})
        return self.create(vals)
