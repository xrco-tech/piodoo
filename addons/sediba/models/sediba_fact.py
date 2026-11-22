# -*- coding: utf-8 -*-
"""Figures, dates and tags on a finding, and the visual blocks drawn from them.

A finding says something in words. Where it carries a number, a date or a
yes-or-no fact, a researcher writes that down as a fact on the finding, so a
block can draw it without anyone guessing a figure out of a sentence.

Six blocks are drawn from facts: headline numbers, comparison bars, dates to
know, organisation cards, tags and logos. Only facts on verified findings are
drawn, every item says which finding it came from, and the same facts can
always be read as plain lines.
"""
from math import floor, log10

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import format_date

DATE_FORMAT = 'd MMM y'
FACT_KINDS = [
    ('headline', 'Headline number'),
    ('measure', 'Figure to compare'),
    ('date', 'Date to know'),
    ('tag', 'Tag'),
]
# The parts of a topic's visual summary a doc can show.
BLOCKS = [
    ('all', 'Whole summary'),
    ('tiles', 'Headline numbers'),
    ('bars', 'Comparison bars'),
    ('dates', 'Dates to know'),
    ('orgs', 'Organisation cards'),
]
MAX_TILES = 4
MAX_SERIES = 2
MAX_LINES = 4
MAX_TAGS = 2


def _number(value):
    """12.0 as 12, 1.5 as 1.5: a figure the way a person writes it."""
    return ('%.2f' % value).rstrip('0').rstrip('.')


def _nice(top):
    """The end of a scale: the first round number at or above the largest value."""
    if top <= 0:
        return 1.0
    size = 10 ** floor(log10(top))
    for step in (1, 2, 4, 5, 10):
        if top <= step * size:
            return float(step * size)
    return float(10 * size)


class SedibaOrganisation(models.Model):
    _inherit = 'sediba.organisation'

    logo = fields.Image(max_width=256, max_height=256,
                        help="Uploaded once, then shown beside the organisation's name in every block. "
                             "Until there is one, a square with the first letter of the name stands in.")


class SedibaFinding(models.Model):
    _inherit = 'sediba.finding'

    fact_ids = fields.One2many('sediba.fact', 'finding_id', string="Figures, dates and tags")


class SedibaFact(models.Model):
    _name = 'sediba.fact'
    _description = 'Figure, date or tag on a finding'
    _order = 'finding_id, sequence, id'

    finding_id = fields.Many2one('sediba.finding', required=True, index=True, ondelete='cascade')
    topic_id = fields.Many2one(related='finding_id.topic_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection(FACT_KINDS, required=True, default='measure')
    label = fields.Char(string="What", required=True,
                        help="Headline number: what the figure is, for example 'Cheapest flagship found'. "
                             "Figure to compare: what is measured, the same words on every row of one chart, "
                             "for example 'Price per million tokens, US$'. Date: what happens. Tag: the tag's words.")
    subject = fields.Char(string="About",
                          help="The thing the fact is about, for example a product or a plan.")
    organisation_id = fields.Many2one('sediba.organisation', string="Organisation", ondelete='restrict')
    series = fields.Char(string="Measure",
                         help="When one chart compares two measures, which one this is, for example 'Input' "
                              "or 'Output'. A chart draws two at most.")
    value = fields.Float(string="Number", help="The figure as a plain number, so bars can be drawn to scale.")
    shown = fields.Char(string="Written as",
                        help="The figure as it should read, for example '$8' or 'from $0.10'.")
    date = fields.Date()
    tag = fields.Char(string="Short tag", help="One or two words on a date, for example 'Launch'.")
    action = fields.Boolean(string="Needs action",
                            help="On a date: something has to be done before it. On a tag: it needs attention. "
                                 "Shown in amber, always with words.")

    @api.constrains('kind', 'subject', 'value', 'shown', 'date')
    def _check_complete(self):
        for fact in self:
            if fact.kind == 'headline' and not (fact.shown or '').strip():
                raise ValidationError(_(
                    "The headline number '%s' needs its figure, in 'Written as'.", fact.label))
            if fact.kind == 'measure' and not (fact.subject or '').strip():
                raise ValidationError(_(
                    "The figure '%s' needs what it is about, for example a product name.", fact.label))
            if fact.kind == 'measure' and fact.value < 0:
                raise ValidationError(_(
                    "The figure '%s' is below zero. Bars are drawn from zero, so write it as a tag instead.",
                    fact.label))
            if fact.kind == 'date' and not fact.date:
                raise ValidationError(_("The date to know '%s' needs its date.", fact.label))

    def _text(self):
        """A fact as one plain line, for a finding's page."""
        self.ensure_one()
        about = ", ".join(part for part in (self.subject, self.organisation_id.name) if part)
        if self.kind == 'headline':
            return "%s: %s%s" % (self.label, self.shown, about and " (%s)" % about or '')
        if self.kind == 'measure':
            what = "%s, %s" % (self.label, self.series) if self.series else self.label
            return "%s: %s: %s" % (about, what, self.shown or _number(self.value))
        if self.kind == 'date':
            day = format_date(self.env, self.date, date_format=DATE_FORMAT)
            return "%s: %s%s" % (day, self.label, about and " (%s)" % about or '')
        return "%s%s" % (about and "%s: " % about or '', self.label)


class SedibaTopic(models.Model):
    _inherit = 'sediba.topic'

    def _visual(self):
        """What the blocks draw for this topic, from facts on its verified
        findings only. False when there is nothing to draw."""
        self.ensure_one()
        facts = self.env['sediba.fact'].search([
            ('topic_id', '=', self.id), ('finding_id.status', '=', 'verified'),
            ('finding_id.active', '=', True)], order='sequence, id')
        if not facts:
            return False
        today = fields.Date.context_today(self)
        day = lambda value: format_date(self.env, value, date_format=DATE_FORMAT)
        logo = lambda org: {'id': org.id, 'name': org.name, 'has_logo': bool(org.logo),
                            'letter': (org.name or '?').strip()[:1].upper()} if org else False

        # 1. Headline numbers
        tiles = [{
            'label': fact.label,
            'figure': fact.shown,
            'about': ", ".join(part for part in (fact.subject, fact.organisation_id.name) if part),
            'finding': fact.finding_id.id,
        } for fact in facts.filtered(lambda f: f.kind == 'headline')[:MAX_TILES]]

        # 2. Comparison bars: one chart for each thing measured
        measures = facts.filtered(lambda f: f.kind == 'measure')
        known = []  # every subject the topic's facts name, in order
        for fact in facts.filtered(lambda f: f.kind in ('measure', 'tag') and f.subject):
            if fact.subject not in known:
                known.append(fact.subject)
        charts, figure_of = [], {}
        for label in dict.fromkeys(measures.mapped('label')):
            group = measures.filtered(lambda f, l=label: f.label == l)
            names = list(dict.fromkeys(fact.series or '' for fact in group))
            series, left_out = names[:MAX_SERIES], [name for name in names[MAX_SERIES:] if name]
            rows = {}
            for fact in group:
                if (fact.series or '') not in series:
                    continue
                row = rows.setdefault(fact.subject, {
                    'subject': fact.subject, 'org': logo(fact.organisation_id),
                    'finding': fact.finding_id.id, 'values': [None] * len(series), 'written': [None] * len(series)})
                at = series.index(fact.series or '')
                if row['values'][at] is None:
                    row['values'][at] = fact.value
                    row['written'][at] = fact.shown or _number(fact.value)
            top = _nice(max(value for row in rows.values() for value in row['values'] if value is not None))
            ordered = sorted(rows.values(), key=lambda row: (
                -(row['values'][-1] if row['values'][-1] is not None else -1),
                -(row['values'][0] if row['values'][0] is not None else -1)))
            for row in ordered:
                row['shown'] = " / ".join(text for text in row.pop('written') if text)
                row['bars'] = [{'series': name, 'value': value,
                                'percent': round(value / top * 100, 2) if value is not None else 0}
                               for name, value in zip(series, row.pop('values')) if value is not None]
                figure_of.setdefault(row['subject'], row['shown'])
            charts.append({
                'label': label,
                'series': [name for name in series if name],
                'rows': ordered,
                'ticks': [_number(top * part / 4) for part in range(5)],
                'sorted_by': series[-1] if len(series) > 1 else '',
                'not_drawn': [subject for subject in known if subject not in rows],
                'left_out': left_out,
            })

        # 3. Dates to know, oldest first
        dates = [{
            'date': day(fact.date),
            'label': fact.label,
            'tag': fact.tag or '',
            'act': bool(fact.action and fact.date >= today),
            'finding': fact.finding_id.id,
        } for fact in facts.filtered(lambda f: f.kind == 'date').sorted(lambda f: (f.date, f.sequence, f.id))]

        # 4. Organisation cards
        orgs = []
        for org in facts.mapped('organisation_id'):
            own = facts.filtered(lambda f, o=org: f.organisation_id == o)
            subjects = list(dict.fromkeys(
                fact.subject for fact in own if fact.kind in ('measure', 'tag') and fact.subject))
            tags = [{'label': _("%(what)s, %(date)s", what=fact.label, date=day(fact.date)), 'act': True}
                    for fact in own if fact.kind == 'date' and fact.action and fact.date >= today]
            tags += [{'label': fact.label, 'act': fact.action} for fact in own if fact.kind == 'tag']
            tags.sort(key=lambda tag: not tag['act'])
            seen, kept = set(), []
            for tag in tags:
                if tag['label'] not in seen:
                    seen.add(tag['label'])
                    kept.append(tag)
            if not subjects and not kept:
                continue
            orgs.append({
                'org': logo(org),
                'lines': [{'subject': subject, 'shown': figure_of.get(subject, False)}
                          for subject in subjects[:MAX_LINES]],
                'more': max(0, len(subjects) - MAX_LINES),
                'tags': kept[:MAX_TAGS],
                'finding': own[0].finding_id.id,
            })
        return {'tiles': tiles, 'charts': charts, 'dates': dates, 'orgs': orgs}

    @api.model
    def _visual_part(self, visual, block='all'):
        """One block of a visual summary ('all' keeps everything). False when
        that block has nothing in it."""
        if not visual:
            return False
        keep = {'tiles': ('tiles',), 'bars': ('charts',), 'dates': ('dates',), 'orgs': ('orgs',)}.get(block)
        part = {key: (rows if not keep or key in keep else []) for key, rows in visual.items()}
        return part if any(part.values()) else False

    @api.model
    def _visual_lines(self, visual):
        """The same facts as plain lines: the Text view of a block, what
        prints, and what an assistant reads."""
        lines = []
        if not visual:
            return lines
        for tile in visual['tiles']:
            lines.append("%s: %s%s" % (tile['label'], tile['figure'], tile['about'] and " (%s)" % tile['about'] or ''))
        for chart in visual['charts']:
            head = chart['label'] + (" (%s)" % " / ".join(chart['series']) if chart['series'] else '')
            for row in chart['rows']:
                who = ", ".join(part for part in (row['subject'], row['org'] and row['org']['name']) if part)
                lines.append("%s: %s: %s" % (head, who, row['shown']))
            if chart['not_drawn']:
                lines.append(_("%(what)s: no figure found for %(names)s.",
                               what=chart['label'], names=", ".join(chart['not_drawn'])))
        for date in visual['dates']:
            tag = _("Act before this") if date['act'] else date['tag']
            lines.append("%s: %s%s" % (date['date'], date['label'], tag and " (%s)" % tag or ''))
        for card in visual['orgs']:
            said = ["%s %s" % (line['subject'], line['shown'] or _("[no figure found]")) for line in card['lines']]
            said += [tag['label'] for tag in card['tags']]
            lines.append("%s: %s" % (card['org']['name'], "; ".join(said)))
        return lines
