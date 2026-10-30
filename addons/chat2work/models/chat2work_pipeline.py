# -*- coding: utf-8 -*-
"""Candidate pipeline: the stage behind the Candidates kanban.

The first stages follow what the candidate does (CV page, callback requests);
the rest are set by agents as they work with the candidate. Automatic moves
only go between the automatic stages, so they never undo an agent's move.
Activities and the chatter hold outreach (calls to make, call notes).
"""

from odoo import api, fields, models

from .chat2work_ussd import ID_LIKE, ID_REDACTED

STAGES = [
    ('new', 'New'),
    ('help', 'Needs help'),
    ('cv_ready', 'CV ready'),
    ('screened', 'Screened'),
    ('put_forward', 'Put forward'),
    ('placed', 'Placed'),
    ('not_available', 'Not available'),
]
# target stage -> stages it may be moved from automatically
AUTO_FROM = {
    'help': ('new', 'cv_ready'),
    'cv_ready': ('new', 'help'),
}
CV_DONE = ('uploaded', 'built')
PROVINCES = [
    ('gauteng', 'Gauteng'),
    ('kzn', 'KwaZulu-Natal'),
    ('western_cape', 'Western Cape'),
    ('eastern_cape', 'Eastern Cape'),
    ('limpopo', 'Limpopo'),
    ('mpumalanga', 'Mpumalanga'),
    ('north_west', 'North West'),
    ('free_state', 'Free State'),
    ('northern_cape', 'Northern Cape'),
]
# Shorter "text" is only the file type Odoo stores for a file it can't read.
CV_TEXT_MIN = 30


class Chat2workCandidatePipeline(models.Model):
    _name = 'chat2work.candidate'
    _inherit = ['chat2work.candidate', 'mail.thread', 'mail.activity.mixin']

    stage = fields.Selection(STAGES, default='new', required=True, index=True, tracking=True,
                             group_expand='_expand_stages')
    callback_ids = fields.One2many('chat2work.callback.request', 'candidate_id', 'Callback Requests')
    open_callback_count = fields.Integer('Open Callbacks', compute='_compute_open_callback_count')
    province = fields.Selection(PROVINCES, index=True)
    cv_text = fields.Text('CV Text', compute='_compute_cv_text', store=True, copy=False,
                          help="Text read from the CV file, for matching to job listings. ID numbers removed.")
    cv_text_state = fields.Selection([
        ('none', 'No CV file'),
        ('readable', 'Readable'),
        ('unreadable', 'Not readable (photo or scan)'),
    ], 'CV Text Status', compute='_compute_cv_text', store=True, copy=False)

    @api.depends('cv_attachment_id')
    def _compute_cv_text(self):
        for rec in self:
            attachment = rec.cv_attachment_id.sudo()
            text = (attachment.index_content or '').strip() if attachment else ''
            readable = len(text) >= CV_TEXT_MIN
            rec.cv_text = ID_LIKE.sub(ID_REDACTED, text) if readable else False
            rec.cv_text_state = 'readable' if readable else 'unreadable' if attachment else 'none'

    @api.model
    def _expand_stages(self, states, domain):
        return [key for key, _label in STAGES]

    @api.depends('callback_ids.state')
    def _compute_open_callback_count(self):
        for rec in self:
            rec.open_callback_count = len(rec.callback_ids.filtered(lambda c: c.state in ('new', 'in_progress')))

    def _c2w_auto_stage(self, target):
        """Move to `target` the candidates still in a stage it may replace."""
        movable = self.filtered(lambda r: r.stage in AUTO_FROM[target])
        if movable:
            movable.sudo().write({'stage': target})

    def write(self, vals):
        res = super().write(vals)
        if 'stage' not in vals:
            if vals.get('cv_state') in CV_DONE:
                self._c2w_auto_stage('cv_ready')
            elif vals.get('cv_state') == 'help_requested':
                self._c2w_auto_stage('help')
        return res

    def action_open_callbacks(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('chat2work.action_chat2work_callback')
        action['domain'] = [('candidate_id', '=', self.id)]
        action['context'] = {'default_candidate_id': self.id, 'default_phone': self.phone}
        return action


class Chat2workCallbackPipeline(models.Model):
    _inherit = 'chat2work.callback.request'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.candidate_id._c2w_auto_stage('help')
        return records
