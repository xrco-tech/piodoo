# -*- coding: utf-8 -*-

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ContactCentreMessage(models.Model):
    _inherit = 'contact.centre.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._notify_inbox_agents()
        return records

    def _notify_inbox_agents(self):
        """Push a real-time bus notification to every Contact Centre agent
        so the inbox updates without polling. Single choke point: every
        contact.centre.message, regardless of source (webhook, sync,
        campaign, automation, manual reply), passes through create()."""
        try:
            agent_group = self.env.ref('contact_centre.group_contact_centre_agent', raise_if_not_found=False)
            if not agent_group:
                return
            users = self.env['res.users'].sudo().search([
                ('active', '=', True),
                ('groups_id', 'in', agent_group.id),
            ])
            if not users:
                return
            bus = self.env['bus.bus'].sudo()
            for record in self:
                payload = {
                    'contact_id': record.contact_id.id,
                    'message_id': record.id,
                    'channel': record.channel,
                    'direction': record.direction,
                    'body_preview': (record.body_text or '')[:120],
                    'message_timestamp': str(record.message_timestamp) if record.message_timestamp else False,
                }
                for user in users:
                    partner = user.partner_id
                    if not partner:
                        continue
                    try:
                        bus._sendone(partner, 'contact_centre_new_message', payload)
                    except AttributeError:
                        _logger.warning("contact_centre_inbox: bus.bus._sendone missing; cannot notify user %s", user.id)
                        return
        except Exception as e:
            _logger.error("contact_centre_inbox: failed to send bus notification: %s", e, exc_info=True)
