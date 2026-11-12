# -*- coding: utf-8 -*-
"""What the Templates section of the workspace reads and writes: the message
templates of every channel (WhatsApp, SMS, email), where each is used, and
writing, correcting and archiving one.

Agents can look; only managers can change a template. Nothing here sends."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .contact_centre_workspace_campaigns import MANAGER

TEMPLATE = 'contact.centre.template'
CHANNELS = ('whatsapp', 'sms', 'email')


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _template(self, template_id):
        template = self.env[TEMPLATE].with_context(active_test=False).search([('id', '=', int(template_id or 0))], limit=1)
        if not template:
            raise UserError(_("This template no longer exists."))
        return template

    def _template_manager(self):
        self._agent()
        if not self.env.user.has_group(MANAGER):
            raise AccessError(_("Only Contact Centre managers can change a template."))

    # ── The list ─────────────────────────────────────────────────────────
    @api.model
    def ws_templates(self, pill='all', search='', offset=0, limit=40):
        self._agent()
        domain = [('active', '=', pill != 'archived')]
        if pill in CHANNELS:
            domain.append(('channel', '=', pill))
        term = (search or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('body_text', 'ilike', term)]
        Template = self.env[TEMPLATE].with_context(active_test=False)
        total = Template.search_count(domain)
        templates = Template.search(domain, order='name, id', offset=int(offset), limit=int(limit))
        labels = self._labels(TEMPLATE, 'channel')
        return {
            'rows': [{
                'id': template.id,
                'name': template.name,
                'channel': template.channel,
                'channel_label': labels.get(template.channel, ''),
                'preview': self._preview(template.body_text),
                'active': template.active,
            } for template in templates],
            'total': total,
            'more': total > int(offset) + len(templates),
            'can_manage': self.env.user.has_group(MANAGER),
        }

    # ── One template ─────────────────────────────────────────────────────
    @api.model
    def ws_template(self, template_id):
        self._agent()
        template = self._template(template_id)
        self._flush()
        Message = self.env['contact.centre.message']
        sent = Message.search_count([('template_id', '=', template.id)])
        last = Message.search([('template_id', '=', template.id)], order='message_timestamp desc, id desc', limit=1)
        campaigns = self.env['contact.centre.campaign'].with_context(active_test=False).search(
            [('template_id', '=', template.id)], order='id desc')
        automations = self.env['contact.centre.automation'].with_context(active_test=False).search(
            [('template_id', '=', template.id)], order='sequence, id')
        states = self._labels('contact.centre.campaign', 'state')
        native = template.wa_template_id
        return {
            'id': template.id,
            'name': template.name,
            'channel': template.channel,
            'channel_label': self._labels(TEMPLATE, 'channel').get(template.channel, ''),
            'body': template.body_text or '',
            'notes': template.notes or '',
            'active': template.active,
            'sent': sent,
            'last_sent': fields.Datetime.to_string(last.message_timestamp) if last else False,
            'campaigns': [{
                'id': campaign.id, 'name': campaign.name, 'state': states.get(campaign.state, ''),
                'running': campaign.state == 'running',
            } for campaign in campaigns],
            'automations': [{
                'id': automation.id, 'name': automation.name, 'campaign': automation.campaign_id.name or '',
                'active': automation.active,
            } for automation in automations],
            # The approved WhatsApp template this one is tied to, when there is one.
            'native': {
                'name': native.display_name,
                'status': self._labels('whatsapp.template', 'status').get(native.status, '') if native.status else '',
                'approved': native.status == 'APPROVED',
            } if native else False,
            'can_manage': self.env.user.has_group(MANAGER),
        }

    # ── Changing a template ──────────────────────────────────────────────
    @api.model
    def _template_values(self, vals, template=None):
        clean = {}
        if 'name' in vals:
            clean['name'] = ' '.join((vals['name'] or '').split())
            if not clean['name']:
                raise UserError(_("A template needs a name."))
        if 'body_text' in vals:
            clean['body_text'] = (vals['body_text'] or '').strip()
            if not clean['body_text']:
                raise UserError(_("A template needs a message."))
        if 'channel' in vals:
            if vals['channel'] not in CHANNELS:
                raise UserError(_("Choose WhatsApp, SMS or email."))
            clean['channel'] = vals['channel']
        if 'notes' in vals:
            clean['notes'] = (vals['notes'] or '').strip() or False
        if template and clean.get('channel', template.channel) != template.channel:
            # A campaign sends its template on the campaign's own channel.
            used = self.env['contact.centre.campaign'].with_context(active_test=False).search_count(
                [('template_id', '=', template.id)])
            if used:
                raise UserError(_("This template is used by a campaign, so its channel can't change. Make a new template instead."))
        return clean

    @api.model
    def ws_template_save(self, template_id, vals):
        """Write a new template (no id) or correct an existing one."""
        self._template_manager()
        vals = vals or {}
        if template_id:
            template = self._template(template_id)
            clean = self._template_values(vals, template)
            if clean:
                template.write(clean)
        else:
            missing = [key for key in ('name', 'channel', 'body_text') if key not in vals]
            clean = self._template_values(dict(vals, **dict.fromkeys(missing, False)))
            template = self.env[TEMPLATE].create(clean)
        return self.ws_template(template.id)

    @api.model
    def ws_template_archive(self, template_id, archive=True):
        """Archive a template (it is no longer offered when sending) or bring it back."""
        self._template_manager()
        template = self._template(template_id)
        template.write({'active': not archive})
        return self.ws_template(template.id)
