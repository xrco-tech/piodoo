# -*- coding: utf-8 -*-
"""Click-through preview of the Chat2Work USSD flow, inside Odoo.

Nothing is saved: every turn replays the whole key sequence through the real
engine (chat2work.ussd.session.ussd_handle) inside a savepoint that is then
rolled back. Profiles, status updates and callbacks only ever exist for the
length of the replay, and SMS sending is skipped via context.

Built as a form dialog (not an OWL client action) on purpose — see the
client-action rendering outage noted in the piodoo handoff.
"""

import uuid

from markupsafe import Markup, escape

from odoo import api, fields, models


class _Rollback(Exception):
    pass


class Chat2workUssdSimulator(models.TransientModel):
    _name = 'chat2work.ussd.simulator'
    _description = 'Chat2Work USSD Simulator'

    account_id = fields.Many2one(
        'comm.ussd.account', 'USSD Account',
        domain=[('flow_engine', '=', 'chat2work')],
        default=lambda self: self._default_account())
    service_code = fields.Char(related='account_id.service_code')
    phone = fields.Char(
        'Caller MSISDN', required=True, default='+27600000000',
        help="Use a number with an existing candidate profile to preview the "
             "returning-caller menu.")
    # Not default=list: Odoo calls defaults with the record, so list(record)
    # would yield [record] on a new (unsaved) dialog record.
    inputs = fields.Json(default=lambda self: [])
    user_input = fields.Char('Reply')
    ended = fields.Boolean(readonly=True)
    screen_html = fields.Html(compute='_compute_screen_html', sanitize=False)

    @api.model
    def _default_account(self):
        return self.env['comm.ussd.account'].search(
            [('flow_engine', '=', 'chat2work')], limit=1)

    # ── Replay ───────────────────────────────────────────────────────────────

    def _replay(self):
        """Run the session from the start; return the response for every turn."""
        self.ensure_one()
        Session = self.env['chat2work.ussd.session'].with_context(chat2work_ussd_simulation=True)
        code = self.service_code or '*000#'
        sid = 'SIM-' + uuid.uuid4().hex
        responses = []
        try:
            with self.env.cr.savepoint():
                responses.append(Session.ussd_handle(sid, code, self.phone, '', ''))
                crumbs = []
                for inp in self.inputs or []:
                    crumbs.append(inp)
                    responses.append(Session.ussd_handle(sid, code, self.phone, '*'.join(crumbs), inp))
                # Push pending ORM writes into the savepoint so the rollback
                # discards them too, instead of them flushing afterwards.
                self.env.flush_all()
                raise _Rollback()
        except _Rollback:
            pass
        self.env.invalidate_all()
        return responses

    @api.depends('inputs', 'phone', 'account_id')
    def _compute_screen_html(self):
        for wiz in self:
            if not wiz.phone:
                wiz.screen_html = False
                continue
            wiz.screen_html = wiz._render_transcript(wiz._replay(), wiz.inputs or [])

    @staticmethod
    def _render_transcript(responses, inputs):
        bubble = ('<div style="background:#1f2a1f;color:#d7f5d7;font-family:monospace;'
                  'white-space:pre-wrap;padding:10px 12px;border-radius:8px;'
                  'margin:6px 0;max-width:340px;{extra}">{text}</div>')
        reply = ('<div style="text-align:right;max-width:340px;margin:2px 0 8px;">'
                 '<span style="background:#e8eefc;color:#1d3b8b;font-family:monospace;'
                 'padding:3px 10px;border-radius:10px;">{text}</span></div>')
        parts = []
        for i, resp in enumerate(responses):
            kind, _, body = resp.partition(' ')
            last = i == len(responses) - 1
            extra = 'border:2px solid #6fcf6f;' if last else 'opacity:.55;'
            tag = ('<div style="font-size:11px;color:#888;max-width:340px;">%s · %d chars</div>'
                   % (kind, len(resp)))
            parts.append(Markup(tag) + Markup(bubble.format(extra=extra, text=escape(body))))
            if i < len(inputs):
                parts.append(Markup(reply.format(text=escape(inputs[i] or '(empty)'))))
        return Markup('').join(parts)

    # ── Buttons ──────────────────────────────────────────────────────────────

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': 'USSD Simulator',
        }

    def action_send(self):
        self.ensure_one()
        if self.ended:
            return self._reopen()
        inputs = list(self.inputs or []) + [(self.user_input or '').strip()]
        self.write({'inputs': inputs, 'user_input': False})
        last = self._replay()[-1]
        self.ended = last.startswith('END')
        return self._reopen()

    def action_restart(self):
        self.write({'inputs': [], 'user_input': False, 'ended': False})
        return self._reopen()
