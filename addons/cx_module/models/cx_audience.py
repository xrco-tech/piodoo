# -*- coding: utf-8 -*-
"""UCX Audiences / Segments.

A saved res.partner filter (name + domain) that campaigns can point at instead
of hand-writing a domain. Selecting a segment on a campaign copies its filter
into the campaign's audience_domain, so the existing comm_campaign audience
resolution (snapshot / dynamic) keeps working unchanged.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class CxAudience(models.Model):
    _name = 'cx.audience'
    _description = 'UCX Audience / Segment'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    description = fields.Text(help='What this segment is for.')
    domain = fields.Char(
        string='Contact filter', required=True, default='[]',
        help='Odoo domain on res.partner defining who belongs to this segment.')
    partner_count = fields.Integer(
        string='Contacts', compute='_compute_partner_count')
    campaign_ids = fields.One2many('comm.campaign', 'cx_audience_id',
                                   string='Campaigns using this segment')
    campaign_count = fields.Integer(compute='_compute_campaign_count')

    @api.depends('domain')
    def _compute_partner_count(self):
        for aud in self:
            try:
                aud.partner_count = self.env['res.partner'].search_count(
                    aud._eval_domain())
            except (ValueError, SyntaxError, KeyError, TypeError):
                aud.partner_count = 0

    @api.depends('campaign_ids')
    def _compute_campaign_count(self):
        for aud in self:
            aud.campaign_count = len(aud.campaign_ids)

    def _eval_domain(self):
        """Parse the stored domain safely into a list, or raise."""
        self.ensure_one()
        dom = safe_eval(self.domain or '[]', {'uid': self.env.uid})
        if not isinstance(dom, list):
            raise ValidationError(_('The contact filter must be a domain list, '
                                    'e.g. [("customer_rank", ">", 0)].'))
        return dom

    @api.constrains('domain')
    def _check_domain(self):
        for aud in self:
            try:
                self.env['res.partner'].search_count(aud._eval_domain())
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(_('Invalid contact filter: %s') % e)

    def action_cx_preview_contacts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contacts in “%s”') % self.name,
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': self._eval_domain(),
            'target': 'current',
        }


class CxCampaignAudience(models.Model):
    _inherit = 'comm.campaign'

    cx_audience_id = fields.Many2one(
        'cx.audience', string='Audience / Segment', ondelete='set null',
        help='Pick a saved segment to reuse its contact filter instead of '
             'writing a domain below. Selecting one fills the audience filter.')

    @api.onchange('cx_audience_id')
    def _onchange_cx_audience_id(self):
        if self.cx_audience_id:
            self.audience_domain = self.cx_audience_id.domain

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('cx_audience_id') and not vals.get('audience_domain'):
                aud = self.env['cx.audience'].browse(vals['cx_audience_id'])
                if aud.exists():
                    vals['audience_domain'] = aud.domain
        return super().create(vals_list)

    def write(self, vals):
        # When the segment is (re)assigned, refresh the domain from it — unless
        # the caller is explicitly setting a domain in the same write.
        if vals.get('cx_audience_id') and 'audience_domain' not in vals:
            aud = self.env['cx.audience'].browse(vals['cx_audience_id'])
            if aud.exists():
                vals['audience_domain'] = aud.domain
        return super().write(vals)
