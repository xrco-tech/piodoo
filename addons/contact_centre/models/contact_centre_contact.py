# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ContactCentreContact(models.Model):
    """
    Contact Centre contact linked to res.partner.
    """
    _name = 'contact.centre.contact'
    _description = 'Contact Centre Contact'
    _rec_name = 'name'

    partner_id = fields.Many2one(
        'res.partner',
        'Partner',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(
        'Name',
        related='partner_id.name',
        store=True,
        readonly=False,
    )
    phone_number = fields.Char(
        'Phone Number',
        related='partner_id.mobile',
        store=True,
        readonly=False,
    )
    email = fields.Char(
        'Email',
        related='partner_id.email',
        store=True,
        readonly=False,
    )
    # Meta's business-scoped user ID (e.g. "US.13491208655302741918") —
    # rolling out alongside optional WhatsApp usernames. Phone number
    # stays authoritative for now; this is captured in parallel wherever
    # a contact is resolved from a WhatsApp webhook, so identity isn't
    # lost once phone-number fields start getting omitted from webhooks
    # for users who've adopted a username and gone quiet for 30+ days.
    # Lives here rather than on res.partner because this module doesn't
    # depend on comm_whatsapp (see that module's res_partner.py for the
    # equivalent field used by the comm_whatsapp-dependent modules).
    # See: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/
    bsuid = fields.Char(
        'WhatsApp Business-Scoped User ID', index=True,
        help="Meta's business-scoped user ID for this contact, when known.",
    )
    # Computed (not manually written) so it can never drift out of sync -
    # it used to be set by hand in contact.centre.message's create()
    # override, which only covered brand-new messages: an existing
    # message getting updated (e.g. a call's message record patched when
    # the call ends) never refreshed it, and an out-of-order create could
    # silently overwrite a newer value with an older one. message_timestamp
    # already unifies both channels - _sync_whatsapp_call sets it from
    # call_timestamp - so this one field covers "most recent call or
    # message" for free.
    last_contact_date = fields.Datetime(
        'Last Contact Date', compute='_compute_last_contact_date', store=True, index=True,
    )
    tag_ids = fields.Many2many(
        'contact.centre.tag',
        'contact_centre_contact_tag_rel',
        'contact_id',
        'tag_id',
        string='Tags',
    )
    centre_message_ids = fields.One2many(
        'contact.centre.message',
        'contact_id',
        string='Messages',
    )
    campaign_ids = fields.Many2many(
        'contact.centre.campaign',
        'contact_centre_campaign_contact_rel',
        'contact_id',
        'campaign_id',
        string='Campaigns',
    )
    message_count = fields.Integer('Message Count', compute='_compute_message_count')
    campaign_count = fields.Integer('Campaign Count', compute='_compute_campaign_count')

    @api.depends('centre_message_ids.message_timestamp')
    def _compute_last_contact_date(self):
        for contact in self:
            contact.last_contact_date = max(
                contact.centre_message_ids.mapped('message_timestamp'), default=False
            )

    @api.depends('centre_message_ids')
    def _compute_message_count(self):
        for contact in self:
            contact.message_count = len(contact.centre_message_ids)

    @api.depends('campaign_ids')
    def _compute_campaign_count(self):
        for contact in self:
            contact.campaign_count = len(contact.campaign_ids)

    def action_view_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Messages',
            'res_model': 'contact.centre.message',
            'view_mode': 'list,form',
            'domain': [('contact_id', '=', self.id)],
            'context': {'default_contact_id': self.id},
        }


class ContactCentreTag(models.Model):
    """Tags for organizing contacts"""
    _name = 'contact.centre.tag'
    _description = 'Contact Centre Tag'

    name = fields.Char('Tag Name', required=True)
    color = fields.Integer('Color', default=1)
    active = fields.Boolean('Active', default=True)
