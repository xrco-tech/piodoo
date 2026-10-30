# -*- coding: utf-8 -*-
"""CV designs, and the plain view of a candidate's answers they all render."""

import re

from odoo import api, fields, models

FALLBACK_LAYOUT = 'chat2work_cv_templates.layout_classic'
NO_LICENCE = {'', 'none'}


def _split_list(text):
    return [part.strip() for part in re.split(r'[,;\n]', text or '') if part.strip()]


def _split_duties(text):
    """A candidate's sentences become bullets; a single sentence stays as it is."""
    return [part.strip(' .') for part in re.split(r';|\n|(?<=[.!?])\s+', text or '') if part.strip(' .')]


class Chat2workCvTemplate(models.Model):
    _name = 'chat2work.cv.template'
    _description = 'Chat2Work CV Design'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    key = fields.Char(required=True, help="Names the preview image in static/src/img.")
    best_for = fields.Char('Best For', help="Shown to the candidate under the design's name.")
    layout = fields.Char(required=True, help="XML id of the QWeb template that draws this design.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    preview_url = fields.Char(compute='_compute_preview_url')

    _sql_constraints = [('key_unique', 'unique(key)', 'Each CV design needs its own key.')]

    @api.depends('key')
    def _compute_preview_url(self):
        for rec in self:
            rec.preview_url = '/chat2work_cv_templates/static/src/img/%s.png' % rec.key


class Chat2workCandidate(models.Model):
    _inherit = 'chat2work.candidate'

    cv_template_id = fields.Many2one('chat2work.cv.template', 'CV Design', ondelete='set null', copy=False)

    def _c2w_set_cv_template(self, template_id):
        """Save the design picked on the public form; ignore anything else."""
        self.ensure_one()
        if not str(template_id or '').isdigit():
            return
        template = self.env['chat2work.cv.template'].sudo().search([('id', '=', int(template_id))])
        if template:
            self.sudo().cv_template_id = template

    def _c2w_cv_layout(self):
        """The QWeb template to draw this candidate's CV with."""
        self.ensure_one()
        template = self.sudo().cv_template_id
        if not template.active:  # none chosen, or the design has since been retired
            template = self.env['chat2work.cv.template'].sudo().search([], limit=1)
        layout = template.layout or FALLBACK_LAYOUT
        return layout if self.env.ref(layout, raise_if_not_found=False) else FALLBACK_LAYOUT

    def _c2w_cv_view(self):
        """The form answers tidied for printing, so designs needn't handle gaps."""
        self.ensure_one()
        rec = self.sudo()
        data = rec.cv_data or {}
        experience = []
        for job in data.get('experience') or []:
            title = job.get('role') or job.get('employer')
            if title:
                experience.append({
                    'title': title,
                    'employer': job.get('employer') if job.get('role') else '',
                    'dates': job.get('dates') or '',
                    'duties': _split_duties(job.get('duties')),
                })
        education = []
        for edu in data.get('education') or []:
            title = edu.get('qualification') or edu.get('school')
            if title:
                education.append({
                    'title': title,
                    'school': edu.get('school') if edu.get('qualification') else '',
                    'year': edu.get('year') or '',
                })
        licence = data.get('licence') or ''
        return {
            'name': data.get('full_name') or rec.name or '',
            'phone': rec._c2w_display_phone(),
            'email': data.get('email') or '',
            'town': data.get('town') or rec.location or '',
            'summary': data.get('summary') or '',
            'experience': experience,
            'education': education,
            'skills': _split_list(data.get('skills')),
            'languages': _split_list(data.get('languages')),
            'licence': '' if licence.strip().lower() in NO_LICENCE else licence,
        }

    def action_c2w_rebuild_cv(self):
        """Draw the saved answers again, after an agent changes the design."""
        for rec in self.filtered(lambda r: r.sudo().cv_data):
            rec._c2w_build_cv(rec.sudo().cv_data)
        return True
