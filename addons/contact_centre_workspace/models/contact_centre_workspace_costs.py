# -*- coding: utf-8 -*-
"""What a campaign and a call cost, for the people who may see billing.

Billing is not a dependency of the workspace: without it, or for a user who
cannot read billing, these return False and the screen shows nothing extra.

A campaign's charges are found through its own message log, so they are right
whatever the charge was tagged with: a WhatsApp message by the id Meta gave
it, an SMS by its SMS record."""

from odoo import _, api, models

REPLY_DAYS = 7


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    @api.model
    def _billing(self):
        """The billing ledger when this user may read it, else None."""
        Event = self.env.get('comm.billing.event')
        if Event is None or not Event.has_access('read'):
            return None
        return Event.sudo()

    @api.model
    def _money(self, amount):
        return self.env.company.currency_id.format(amount)

    @api.model
    def _campaign_cost(self, campaign):
        Event = self._billing()
        if Event is None:
            return False
        Event.flush_model()
        self._flush()
        params = {'campaign': campaign.id, 'currency': self.env.company.currency_id.id,
                  'days': REPLY_DAYS}
        self.env.cr.execute("""
            WITH charged AS (
                SELECT e.id
                  FROM contact_centre_message m
                  JOIN whatsapp_message w ON w.message_id = m.provider_message_id
                  JOIN comm_billing_event e
                    ON e.source_model = 'whatsapp.message' AND e.source_id = w.id
                 WHERE m.campaign_id = %(campaign)s AND m.direction = 'outbound'
                   AND COALESCE(m.provider_message_id, '') <> ''
                UNION
                SELECT e.id
                  FROM contact_centre_message m
                  JOIN comm_billing_event e
                    ON e.source_model = 'sms.sms' AND e.source_id = m.sms_id
                 WHERE m.campaign_id = %(campaign)s AND m.direction = 'outbound'
                   AND m.sms_id IS NOT NULL
            )
            SELECT COALESCE(SUM(e.price_local) FILTER (WHERE e.currency_id = %(currency)s), 0),
                   COUNT(*),
                   COUNT(*) FILTER (WHERE e.rate_id IS NULL AND NOT COALESCE(e.is_free, FALSE)),
                   COUNT(*) FILTER (WHERE e.is_free)
              FROM comm_billing_event e
              JOIN charged USING (id)
        """, params)
        cost, charges, unpriced, free = self.env.cr.fetchone()
        # A reply: a contact who wrote back within a week of their campaign message.
        self.env.cr.execute("""
            SELECT COUNT(DISTINCT reply.contact_id)
              FROM contact_centre_message reply
              JOIN (SELECT contact_id, MIN(message_timestamp) AS at
                      FROM contact_centre_message
                     WHERE campaign_id = %(campaign)s AND direction = 'outbound'
                       AND status IN ('sent', 'delivered', 'read')
                     GROUP BY contact_id) sent ON sent.contact_id = reply.contact_id
             WHERE reply.direction = 'inbound'
               AND reply.message_timestamp > sent.at
               AND reply.message_timestamp <= sent.at + make_interval(days => %(days)s)
        """, params)
        replied = self.env.cr.fetchone()[0]
        notes = []
        if not charges:
            notes.append(_("Nothing has been charged for this campaign yet."))
        if unpriced:
            notes.append(_("%s charges have no rate yet and count as zero.", unpriced))
        if free:
            notes.append(_("%s messages went out free of charge.", free))
        return {
            'stats': [
                {'label': _("Replied"), 'value': replied},
                {'label': _("Cost"), 'value': self._money(cost)},
                {'label': _("Per reply"), 'value': self._money(cost / replied) if replied and cost else '—'},
                {'label': _("Charges"), 'value': charges},
            ],
            'note': ' '.join(notes),
            'reply_days': REPLY_DAYS,
        }

    @api.model
    def _call_cost(self, line, call):
        """The charge for one call as text; False when there is none to show.
        Only WhatsApp calls are in the ledger: softphone calls are not billed."""
        Event = self._billing()
        if Event is None or line != 'wa':
            return False
        events = Event.search([('source_model', '=', 'whatsapp.call.log'), ('source_id', '=', call.id)])
        if not events:
            return False
        if all(event.rate_id or event.is_free for event in events):
            company_currency = self.env.company.currency_id
            return self._money(sum(e.price_local for e in events if e.currency_id == company_currency))
        return _("No rate yet")
