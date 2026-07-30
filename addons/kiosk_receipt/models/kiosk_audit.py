# -*- coding: utf-8 -*-
from odoo import models, fields


class KioskAudit(models.Model):
    """A kiosk audit event mirrored into Odoo. Idempotent on `kiosk_ref`."""
    _name = 'kiosk.audit'
    _description = 'Kiosk Audit Event (synced)'
    _order = 'happened_at desc'
    _rec_name = 'event_type'

    kiosk_ref = fields.Char(string='Kiosk Ref', index=True, required=True)
    happened_at = fields.Datetime(string='When')
    event_type = fields.Char(string='Event')
    staff_name = fields.Char(string='Staff')
    staff_ref = fields.Char(string='Staff Ref')
    detail = fields.Char(string='Detail')

    _sql_constraints = [
        ('kiosk_ref_uniq', 'unique(kiosk_ref)', 'This audit event has already been synced.'),
    ]
