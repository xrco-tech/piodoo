# -*- coding: utf-8 -*-
"""What the Contacts section of the workspace reads and writes: the directory
of Contact Centre contacts, one contact's details, tags, campaigns and recent
activity, and adding or correcting a contact.

Everything is done as the signed-in agent, so their own access rights decide
what they may change."""

import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .contact_centre_workspace import COLOURS

EDITABLE = ('name', 'phone_number', 'email')


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _digits(self, value):
        return re.sub(r'\D', '', value or '')

    @api.model
    def _contact_domain(self, pill, search, tag_id):
        domain = []
        if pill == 'recent':
            domain.append(('last_contact_date', '>=', fields.Datetime.now() - timedelta(days=30)))
        elif pill == 'never':
            domain.append(('last_contact_date', '=', False))
        elif pill == 'campaign':
            domain.append(('campaign_ids.state', '=', 'running'))
        if tag_id:
            domain.append(('tag_ids', 'in', [int(tag_id)]))
        term = (search or '').strip()
        if term:
            digits = self._digits(term)
            # "082 555 0142" finds 27825550142: numbers are matched on their last nine digits.
            number = digits[-9:] if len(digits) >= 7 and not re.search(r'[A-Za-z@]', term) else term
            domain += ['|', '|', ('name', 'ilike', term), ('phone_number', 'ilike', number), ('email', 'ilike', term)]
        return domain

    @api.model
    def _contact_values(self, vals):
        """The typed name, phone and email, tidied; raises when nothing would be left to call them by."""
        clean = {}
        for key in EDITABLE:
            if key in vals:
                clean[key] = ' '.join((vals[key] or '').split()) or False
        if clean.get('phone_number'):
            # "082 555-0142" is kept as 0825550142, so it is found again however it is typed.
            clean['phone_number'] = re.sub(r'[\s\-().]', '', clean['phone_number'])
        if clean.get('email') and '@' not in clean['email']:
            raise UserError(_("That email address doesn't look right."))
        if clean.get('phone_number') and len(self._digits(clean['phone_number'])) < 7:
            raise UserError(_("That phone number doesn't look right."))
        return clean

    # ── The list ─────────────────────────────────────────────────────────
    @api.model
    def ws_contacts(self, pill='all', search='', tag_id=False, offset=0, limit=40):
        self._agent()
        Contact = self.env['contact.centre.contact']
        domain = self._contact_domain(pill, search, tag_id)
        order = 'last_contact_date desc nulls last, id desc' if pill == 'recent' else 'name, id'
        total = Contact.search_count(domain)
        contacts = Contact.search(domain, order=order, offset=int(offset), limit=int(limit))
        rows = [{
            'id': contact.id,
            'name': contact.name or contact.phone_number or _("Unknown"),
            'phone': contact.phone_number or '',
            'email': contact.email or '',
            'at': fields.Datetime.to_string(contact.last_contact_date) if contact.last_contact_date else False,
            'tags': contact.tag_ids.mapped('name'),
            'initials': self._initials(contact.name),
            'colour': COLOURS[contact.id % len(COLOURS)],
        } for contact in contacts]
        return {'rows': rows, 'total': total, 'more': total > int(offset) + len(rows)}

    @api.model
    def ws_contact_tags(self):
        """The tags a contact can carry."""
        self._agent()
        return self.env['contact.centre.tag'].search_read([], ['name'], order='name')

    # ── One contact ──────────────────────────────────────────────────────
    @api.model
    def ws_contact(self, contact_id):
        self._agent()
        contact = self._contact(contact_id)
        self._flush()
        Message = self.env['contact.centre.message']
        messages = Message.search([('contact_id', '=', contact.id)], order='message_timestamp desc, id desc', limit=6)
        groups = Message._read_group([('contact_id', '=', contact.id)], ['channel', 'direction'], ['__count'])
        count = lambda test: sum(n for channel, direction, n in groups if test(channel, direction))
        first = Message.search([('contact_id', '=', contact.id)], order='message_timestamp, id', limit=1)
        waiting = self._unread(contact.ids, seen=False).get(contact.id, (0, False))[0]
        Campaign = self.env['contact.centre.campaign']
        states = dict(Campaign._fields['state']._description_selection(self.env))
        channels = dict(Campaign._fields['channel']._description_selection(self.env))
        return {
            'id': contact.id,
            'name': contact.name or '',
            'phone': contact.phone_number or '',
            'email': contact.email or '',
            'partner_id': contact.partner_id.id,
            'initials': self._initials(contact.name),
            'colour': COLOURS[contact.id % len(COLOURS)],
            'state': contact.state or 'open',
            'waiting': waiting,
            'tag_ids': contact.tag_ids.ids,
            'campaigns': [{
                'id': campaign.id, 'name': campaign.name,
                'channel': channels.get(campaign.channel, campaign.channel or ''),
                'state': states.get(campaign.state, campaign.state or ''),
                'running': campaign.state == 'running',
            } for campaign in contact.campaign_ids],
            'stats': [
                {'label': _("Messages"), 'value': count(lambda channel, direction: channel != 'voice')},
                {'label': _("Calls"), 'value': count(lambda channel, direction: channel == 'voice')},
                {'label': _("From them"), 'value': count(lambda channel, direction: direction == 'inbound')},
                {'label': _("From us"), 'value': count(lambda channel, direction: direction == 'outbound')},
            ],
            'first': fields.Datetime.to_string(first.message_timestamp) if first else False,
            'last': fields.Datetime.to_string(contact.last_contact_date) if contact.last_contact_date else False,
            'channels': sorted({self._channel_label(channel) for channel, _direction, _n in groups if channel}),
            'recent': [{
                'id': m.id, 'channel': m.channel, 'out': m.direction == 'outbound',
                'preview': self._preview(m.body_text), 'at': fields.Datetime.to_string(m.message_timestamp),
                'failed': m.status == 'failed',
            } for m in messages],
        }

    # ── Changing a contact ───────────────────────────────────────────────
    @api.model
    def ws_contact_save(self, contact_id, vals):
        """Correct the name, phone number or email. They live on the person's
        own record, so the change shows everywhere that person does."""
        self._agent()
        contact = self._contact(contact_id)
        clean = self._contact_values(vals or {})
        if 'name' in clean and not clean['name']:
            raise UserError(_("A contact needs a name."))
        if clean:
            contact.write(clean)
        return self.ws_contact(contact.id)

    @api.model
    def ws_contact_set_tags(self, contact_id, tag_ids):
        self._agent()
        contact = self._contact(contact_id)
        tags = self.env['contact.centre.tag'].browse([int(t) for t in tag_ids or []]).exists()
        contact.write({'tag_ids': [(6, 0, tags.ids)]})
        return contact.tag_ids.ids

    @api.model
    def ws_contact_create(self, vals):
        """Add a contact. When the number already belongs to one, that contact
        is returned instead of a second one being made."""
        self._agent()
        clean = self._contact_values(dict.fromkeys(EDITABLE, False) | (vals or {}))
        if not clean['name'] and not clean['phone_number']:
            raise UserError(_("Give the contact a name or a phone number."))
        Contact = self.env['contact.centre.contact']
        digits = self._digits(clean['phone_number'])
        if digits:
            existing = Contact.search([('phone_number', 'ilike', digits[-9:])], limit=1)
            if existing:
                return {'id': existing.id, 'existing': True}
        partner = self.env['res.partner'].create({
            'name': clean['name'] or clean['phone_number'],
            'mobile': clean['phone_number'],
            'email': clean['email'],
        })
        return {'id': Contact.create({'partner_id': partner.id}).id, 'existing': False}
