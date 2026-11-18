# -*- coding: utf-8 -*-
"""Sediba: research topics, findings with their sources, and research runs.

No model here inherits mail.thread and no field is tracked, on purpose: an
automated user with no email address has to be able to write findings, and
tracked fields make Odoo post a note that such a user cannot send.
"""
from datetime import timedelta
from random import randint

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

STATUSES = [
    ('lead', 'Lead, not verified'),
    ('verified', 'Verified'),
    ('unconfirmed', 'Could not confirm'),
]

SOURCE_KINDS = [
    ('primary', "Organisation's own page or document"),
    ('official', 'Government or official record'),
    ('news', 'News report'),
    ('sponsored', 'Sponsored content'),
    ('social', 'Social post'),
    ('other', 'Other'),
]

# A source of one of these kinds proves a claim by itself.
STRONG_KINDS = ('primary', 'official')
# How long a verified finding stands before it should be looked at again.
RECHECK_DAYS = 90


class SedibaSpace(models.Model):
    """An app that shows part of the research, for example Chat2Work. A topic
    lists the apps it is relevant to; the workspace opened from inside an app
    shows only those topics and their findings."""
    _name = 'sediba.space'
    _description = 'App that shows research'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="The key the app's menu passes to the workspace.")

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Another app already uses this key.'),
    ]


class SedibaTopic(models.Model):
    _name = 'sediba.topic'
    _description = 'Research topic'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    scope = fields.Text(help="What to look for under this topic.")
    space_ids = fields.Many2many('sediba.space', string="Shown in",
                                 help="The apps this topic is relevant to. It shows in the research "
                                      "screen opened from inside each of them. Sediba itself shows every topic.")
    summary = fields.Text(string="What we know",
                          help="A short summary, drawn only from verified findings.")
    our_read = fields.Text(string="Our read",
                           help="Interpretation, kept apart from the findings.")
    last_researched = fields.Date()
    cycle_days = fields.Integer(string="Research every (days)", default=7)
    due_date = fields.Date(string="Due", compute='_compute_due_date', store=True)
    finding_ids = fields.One2many('sediba.finding', 'topic_id')
    verified_count = fields.Integer(string="Verified", compute='_compute_counts')
    lead_count = fields.Integer(string="Leads", compute='_compute_counts')
    unconfirmed_count = fields.Integer(string="Could not confirm", compute='_compute_counts')

    @api.depends('last_researched', 'cycle_days')
    def _compute_due_date(self):
        for topic in self:
            if topic.last_researched and topic.cycle_days > 0:
                topic.due_date = topic.last_researched + timedelta(days=topic.cycle_days)
            else:
                topic.due_date = False

    @api.depends('finding_ids.status', 'finding_ids.active')
    def _compute_counts(self):
        counts = {}
        if self.ids:
            groups = self.env['sediba.finding']._read_group(
                [('topic_id', 'in', self.ids)], ['topic_id', 'status'], ['__count'])
            counts = {(topic.id, status): count for topic, status, count in groups}
        for topic in self:
            topic.verified_count = counts.get((topic.id, 'verified'), 0)
            topic.lead_count = counts.get((topic.id, 'lead'), 0)
            topic.unconfirmed_count = counts.get((topic.id, 'unconfirmed'), 0)

    def action_open_findings(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sediba.action_sediba_finding')
        action['domain'] = [('topic_id', '=', self.id)]
        action['context'] = {'default_topic_id': self.id}
        action['display_name'] = self.name
        return action


class SedibaOrganisation(models.Model):
    _name = 'sediba.organisation'
    _description = 'Organisation a finding is about'
    _order = 'name'

    name = fields.Char(required=True)
    # Tags with no colour are hidden on board cards, so every one gets a colour.
    color = fields.Integer(default=lambda self: randint(1, 11))

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'This organisation is already listed.'),
    ]


class SedibaFinding(models.Model):
    _name = 'sediba.finding'
    _description = 'Research finding'
    _order = 'needs_review desc, checked_on desc, id desc'

    name = fields.Char(string="Finding", required=True)
    active = fields.Boolean(default=True)
    topic_id = fields.Many2one('sediba.topic', required=True, index=True, ondelete='restrict')
    status = fields.Selection(STATUSES, required=True, default='lead', index=True,
                              group_expand='_expand_statuses')
    statement = fields.Text(string="What it says",
                            help="The claim in plain words, with the figure and the date it refers to.")
    why_it_matters = fields.Text()
    sources_disagree = fields.Boolean(
        help="The sources give different figures. Keep each one on its own line.")
    needs_review = fields.Boolean(string="To review",
                                  help="A person should decide something about this finding.")
    review_note = fields.Char(string="What to decide")
    source_ids = fields.One2many('sediba.source', 'finding_id')
    source_summary = fields.Char(string="Sources", compute='_compute_source_summary')
    organisation_ids = fields.Many2many('sediba.organisation', string="Organisations")
    checked_on = fields.Date()
    checked_by = fields.Char(help="Who looked: a person's name, or the scheduled agent.")
    recheck_by = fields.Date(string="Check again by", compute='_compute_recheck_by',
                             store=True, readonly=False)
    run_id = fields.Many2one('sediba.run', string="Last run", ondelete='set null')
    origin = fields.Char(help="Where a lead came from, for example pasted notes.")
    used_in = fields.Char(help="Where this finding has been used, for example a page or a proposal.")
    ref = fields.Char(string="Reference", copy=False, index=True,
                      help="A short stable key, so an automated run can find this finding again.")

    _sql_constraints = [
        ('ref_uniq', 'unique(ref)', 'Another finding already has this reference.'),
    ]

    @api.model
    def _expand_statuses(self, statuses, domain):
        return [key for key, _label in STATUSES]

    @api.depends('source_ids.name')
    def _compute_source_summary(self):
        for finding in self:
            names = finding.source_ids.mapped('name')
            if len(names) > 3:
                finding.source_summary = _("%s sources", len(names))
            else:
                finding.source_summary = ", ".join(names)

    @api.depends('status', 'checked_on')
    def _compute_recheck_by(self):
        for finding in self:
            if finding.status == 'verified' and finding.checked_on:
                finding.recheck_by = finding.checked_on + timedelta(days=RECHECK_DAYS)
            else:
                finding.recheck_by = False

    def _is_proven(self):
        """A strong source that was opened, or two opened news reports from
        different places. Sponsored content, social posts and anything that
        was not opened never count."""
        self.ensure_one()
        opened = self.source_ids.filtered('opened')
        if opened.filtered(lambda s: s.kind in STRONG_KINDS):
            return True
        news = opened.filtered(lambda s: s.kind == 'news')
        return len(set(news.mapped(lambda s: (s.name or '').strip().lower()))) >= 2

    @api.constrains('status', 'checked_on', 'source_ids')
    def _check_verified(self):
        for finding in self:
            if finding.status != 'verified':
                continue
            if not finding.checked_on:
                raise ValidationError(_(
                    "'%s' cannot be marked verified without the date it was checked.",
                    finding.name))
            if not finding._is_proven():
                raise ValidationError(_(
                    "'%s' cannot be marked verified yet. It needs one source that is the "
                    "organisation's own page or an official record, or two news reports from "
                    "different publishers, and each must have been opened and read. Add the "
                    "sources first, or leave it as a lead.", finding.name))


class SedibaSource(models.Model):
    _name = 'sediba.source'
    _description = 'Source for a finding'
    _order = 'finding_id, sequence, id'

    finding_id = fields.Many2one('sediba.finding', required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Source", required=True,
                       help="Who published it, for example 'Harambee home page'.")
    url = fields.Char(string="Link")
    says = fields.Text(string="What it says")
    figure_date = fields.Char(string="Date of figure",
                              help="The date the figure refers to, as the source gives it. 'Undated' if it gives none.")
    kind = fields.Selection(SOURCE_KINDS, required=True, default='other')
    opened = fields.Boolean(string="Opened and read", default=True,
                            help="Untick when the page was only seen in a search result or could not be opened.")
    read_on = fields.Date()

    @api.constrains('kind', 'opened')
    def _check_finding_still_proven(self):
        self.finding_id._check_verified()

    @api.ondelete(at_uninstall=False)
    def _unlink_keeps_finding_proven(self):
        for finding in self.finding_id.filtered(lambda f: f.status == 'verified'):
            left = finding.source_ids - self
            opened = left.filtered('opened')
            strong = opened.filtered(lambda s: s.kind in STRONG_KINDS)
            news = {(s.name or '').strip().lower() for s in opened if s.kind == 'news'}
            if not strong and len(news) < 2:
                raise ValidationError(_(
                    "Removing this source would leave '%s' verified without proof. "
                    "Move the finding back to leads first.", finding.name))


class SedibaRun(models.Model):
    _name = 'sediba.run'
    _description = 'Research run'
    _order = 'run_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    run_date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    topic_id = fields.Many2one('sediba.topic', required=True, ondelete='restrict')
    researcher = fields.Char(default="Scheduled agent")
    summary = fields.Text(string="What changed")
    verified_count = fields.Integer(string="Verified")
    lead_count = fields.Integer(string="New leads")
    unconfirmed_count = fields.Integer(string="Could not confirm")
    failures = fields.Text(string="What failed",
                           help="Pages or searches that did not load.")
    finding_ids = fields.One2many('sediba.finding', 'run_id', string="Findings last touched by this run")

    @api.depends('run_date', 'topic_id.name')
    def _compute_name(self):
        for run in self:
            run.name = "%s %s" % (run.run_date or '', run.topic_id.name or '')

    @api.model_create_multi
    def create(self, vals_list):
        runs = super().create(vals_list)
        # A run on a topic is what makes the topic "last researched".
        for run in runs:
            topic = run.topic_id
            if not topic.last_researched or topic.last_researched < run.run_date:
                topic.last_researched = run.run_date
        return runs
