# -*- coding: utf-8 -*-
"""What the Campaigns section of the workspace reads: the list of campaigns,
and one campaign with its numbers, contacts, message log and automated
replies. Starting, finishing, cancelling and resetting a campaign go through
the campaign's own methods, as the signed-in user: agents can look, only
managers can change a campaign.

Building a campaign (template, contacts, sending rules) stays on its form."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

MANAGER = 'contact_centre.group_contact_centre_manager'
STATES = ('draft', 'running', 'done', 'cancelled')
TYPES = ('outbound', 'inbound')
ACTIONS = {'start': 'action_start', 'done': 'action_done', 'cancel': 'action_cancel', 'reset': 'action_reset_draft'}
# Which actions make sense from which state.
ALLOWED = {'draft': ('start', 'cancel'), 'running': ('done', 'cancel'), 'done': ('reset',), 'cancelled': ('reset',)}
SENT = ('sent', 'delivered', 'read')


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _labels(self, model, field):
        return dict(self.env[model]._fields[field]._description_selection(self.env))

    @api.model
    def _campaign(self, campaign_id):
        campaign = self.env['contact.centre.campaign'].search([('id', '=', int(campaign_id or 0))], limit=1)
        if not campaign:
            raise UserError(_("This campaign no longer exists."))
        return campaign

    @api.model
    def _campaign_row(self, campaign, labels):
        return {
            'id': campaign.id,
            'name': campaign.name,
            'type': campaign.campaign_type,
            'type_label': labels['type'].get(campaign.campaign_type, ''),
            'channel': campaign.channel,
            'channel_label': labels['channel'].get(campaign.channel, ''),
            'state': campaign.state or 'draft',
            'state_label': labels['state'].get(campaign.state or 'draft', ''),
            'contacts': len(campaign.contact_ids),
            'at': fields.Datetime.to_string(campaign.date_start) if campaign.date_start else False,
        }

    @api.model
    def _campaign_labels(self):
        Campaign = 'contact.centre.campaign'
        return {'type': self._labels(Campaign, 'campaign_type'), 'channel': self._labels(Campaign, 'channel'),
                'state': self._labels(Campaign, 'state')}

    # ── The list ─────────────────────────────────────────────────────────
    @api.model
    def ws_campaigns(self, pill='all', search='', offset=0, limit=40):
        self._agent()
        domain = []
        if pill in STATES:
            domain.append(('state', '=', pill))
        elif pill in TYPES:
            domain.append(('campaign_type', '=', pill))
        term = (search or '').strip()
        if term:
            domain.append(('name', 'ilike', term))
        Campaign = self.env['contact.centre.campaign']
        total = Campaign.search_count(domain)
        # Running first, then drafts, then what is over; the newest first within each.
        campaigns = Campaign.search(domain, order='id desc', limit=2000)
        rank = {'running': 0, 'draft': 1, 'done': 2, 'cancelled': 3}
        campaigns = campaigns.sorted(lambda c: rank.get(c.state, 1))
        page = campaigns[int(offset):int(offset) + int(limit)]
        labels = self._campaign_labels()
        return {
            'rows': [self._campaign_row(campaign, labels) for campaign in page],
            'total': total,
            'more': total > int(offset) + len(page),
            'can_manage': self.env.user.has_group(MANAGER),
        }

    # ── One campaign ─────────────────────────────────────────────────────
    @api.model
    def ws_campaign(self, campaign_id):
        self._agent()
        campaign = self._campaign(campaign_id)
        self._flush()
        Message = self.env['contact.centre.message']
        row = self._campaign_row(campaign, self._campaign_labels())
        outbound = campaign.campaign_type == 'outbound'

        by_status = dict(Message._read_group([('campaign_id', '=', campaign.id)], ['status'], ['__count']))
        total_messages = sum(by_status.values())
        sent = sum(by_status.get(status, 0) for status in SENT)
        delivered = by_status.get('delivered', 0) + by_status.get('read', 0)

        # The latest campaign message to each listed contact says where they stand.
        contacts = campaign.contact_ids[:60]
        latest = {}
        if contacts:
            self.env.cr.execute("""
                SELECT DISTINCT ON (contact_id) contact_id, status, failure_reason
                  FROM contact_centre_message
                 WHERE campaign_id = %s AND contact_id IN %s AND direction = 'outbound'
                 ORDER BY contact_id, message_timestamp DESC, id DESC
            """, [campaign.id, tuple(contacts.ids)])
            latest = {contact_id: (status, reason) for contact_id, status, reason in self.env.cr.fetchall()}
        status_labels = self._labels('contact.centre.message', 'status')
        people = []
        for contact in contacts:
            status, reason = latest.get(contact.id, (False, ''))
            people.append({
                'id': contact.id,
                'name': contact.name or contact.phone_number or _("Unknown"),
                'phone': contact.phone_number or contact.email or '',
                'initials': self._initials(contact.name),
                'status': status or '',
                'status_label': status_labels.get(status, '') if status else '',
                'failure': reason or '',
            })

        log = Message.search([('campaign_id', '=', campaign.id)], order='message_timestamp desc, id desc', limit=8)
        triggers = self._labels('contact.centre.automation', 'trigger_type')
        template = campaign.template_id
        can_manage = self.env.user.has_group(MANAGER)
        row.update({
            'description': campaign.description or '',
            'outbound': outbound,
            'template': {'name': template.name, 'body': template.body_text or ''} if template else False,
            'script': campaign.script_id.name or '',
            'voice_script': campaign.voice_chatbot_id.name or '',
            'started': fields.Datetime.to_string(campaign.date_start) if campaign.date_start else False,
            'ended': fields.Datetime.to_string(campaign.date_end) if campaign.date_end else False,
            'stats': [
                {'label': _("Contacts"), 'value': len(campaign.contact_ids)},
                {'label': _("Sent"), 'value': sent},
                {'label': _("Delivered"), 'value': delivered},
                {'label': _("Failed"), 'value': by_status.get('failed', 0), 'bad': bool(by_status.get('failed'))},
            ] if outbound else [
                {'label': _("Contacts"), 'value': len(campaign.contact_ids)},
                {'label': _("Messages"), 'value': total_messages},
            ],
            # How far the send has got, for an outbound campaign that has been started.
            'progress': {'done': min(campaign.send_progress, len(campaign.contact_ids)), 'total': len(campaign.contact_ids)}
                        if outbound and row['state'] != 'draft' and campaign.contact_ids else False,
            'people': people,
            'people_more': len(campaign.contact_ids) - len(people),
            'log': [{
                'id': m.id, 'name': m.contact_id.name or m.contact_id.phone_number or '',
                'channel': m.channel, 'out': m.direction == 'outbound', 'preview': self._preview(m.body_text),
                'status': m.status or '', 'status_label': status_labels.get(m.status, ''),
                'failure': m.failure_reason or '', 'at': fields.Datetime.to_string(m.message_timestamp),
            } for m in log],
            'automations': [{
                'id': a.id, 'name': a.name, 'active': a.active,
                'trigger': triggers.get(a.trigger_type, ''), 'keyword': a.trigger_keyword or '',
            } for a in campaign.with_context(active_test=False).automation_ids.sorted('sequence')],
            'rules': [
                {'label': _("Delay between messages"), 'value': _("%s s", '%g' % (campaign.throttle_delay or 0))},
                {'label': _("Batches"), 'value': _("%(size)s at a time, %(delay)s s apart", size=campaign.batch_size, delay='%g' % (campaign.batch_delay or 0))
                 if campaign.batch_send else _("All at once")},
            ] if outbound else [],
            'can_manage': can_manage,
            'actions': list(ALLOWED.get(row['state'], ())) if can_manage else [],
        })
        return row

    @api.model
    def ws_campaign_action(self, campaign_id, action):
        """Start, finish, cancel or reset a campaign. Starting an outbound
        campaign begins sending its template to its contacts."""
        self._agent()
        if not self.env.user.has_group(MANAGER):
            raise AccessError(_("Only Contact Centre managers can change a campaign."))
        campaign = self._campaign(campaign_id)
        if action not in ALLOWED.get(campaign.state or 'draft', ()):
            raise UserError(_("That can't be done to a campaign in this state."))
        getattr(campaign, ACTIONS[action])()
        return self.ws_campaign(campaign.id)
