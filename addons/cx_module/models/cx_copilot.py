# -*- coding: utf-8 -*-
"""Phase 7 — AI Copilot, ported from contact_centre_ai_copilot onto the Gen-2
conversation model.

Two deliberate changes from the Gen-1 module:
- reuse comm_chatbot's official `anthropic` SDK path and its
  `comm_chatbot.anthropic_api_key` config parameter, instead of the Gen-1
  raw-requests client keyed on the WhatsApp-specific param;
- run as the calling user (NO sudo). Per the UCX safety posture, the copilot is
  human-launched and its tool/model calls run under the agent's own ACLs — so a
  user who can't read a conversation can't summarise it either.
"""
import logging
import re

from odoo import api, fields, models

try:  # the SDK ships with comm_chatbot's runtime
    import anthropic  # type: ignore
    _ANTHROPIC_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ANTHROPIC_AVAILABLE = False

_logger = logging.getLogger(__name__)

# Default to the current Opus per the claude-api guidance. Thinking is on by
# default on this model and counts against max_tokens, so leave generous
# headroom for the short structured reply.
COPILOT_MODEL = 'claude-opus-5'
COPILOT_MAX_TOKENS = 2048
TRANSCRIPT_LIMIT = 40
_SENTIMENT_VALUES = ('positive', 'neutral', 'negative')


class CommConversation(models.Model):
    _inherit = 'comm.conversation'

    ai_summary = fields.Text('AI Summary', readonly=True)
    ai_sentiment = fields.Selection(
        [('positive', 'Positive'), ('neutral', 'Neutral'), ('negative', 'Negative')],
        string='AI Sentiment', readonly=True)
    ai_suggested_reply = fields.Text('AI Suggested Reply', readonly=True)
    ai_analyzed_date = fields.Datetime('AI Last Analyzed', readonly=True)

    def action_cx_generate_copilot(self):
        """Human-launched: summarise each conversation and suggest a reply.

        Public wrapper so a form button / OWL action can trigger it (Odoo
        blocks buttons from calling private methods). Runs as the current user.
        """
        for conversation in self:
            conversation._cx_generate_copilot()
        return True

    def _cx_generate_copilot(self):
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'comm_chatbot.anthropic_api_key')
        if not (api_key and _ANTHROPIC_AVAILABLE):
            _logger.info('cx copilot: no anthropic key / SDK; skipping conversation %s',
                         self.id)
            return

        interactions = self.env['comm.interaction'].search(
            [('conversation_id', '=', self.id)], order='at desc', limit=TRANSCRIPT_LIMIT)
        if not interactions:
            return
        transcript = "\n".join(
            "%s: %s" % ('Customer' if i.direction == 'inbound' else 'Agent',
                        i.rendered_body or i.raw_body or '')
            for i in reversed(interactions)
        )

        prompt = (
            "You are a contact-centre copilot. Given this conversation transcript, "
            "respond with exactly three sections, each on its own line:\n"
            "SUMMARY: one or two sentence summary of the conversation\n"
            "SENTIMENT: positive, neutral, or negative\n"
            "SUGGESTED_REPLY: a suggested next reply for the agent to send\n\n"
            "Transcript:\n%s" % transcript
        )

        try:
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=COPILOT_MODEL,
                max_tokens=COPILOT_MAX_TOKENS,
                messages=[{'role': 'user', 'content': prompt}],
            )
        except Exception as e:  # pragma: no cover - provider-side failures
            _logger.warning('cx copilot request failed for conversation %s: %s',
                            self.id, e)
            return

        text = "".join(
            getattr(b, 'text', '') for b in resp.content
            if getattr(b, 'type', None) == 'text'
        )
        summary, sentiment, suggested_reply = self._cx_parse_copilot(text)
        self.write({
            'ai_summary': summary,
            'ai_sentiment': sentiment,
            'ai_suggested_reply': suggested_reply,
            'ai_analyzed_date': fields.Datetime.now(),
        })

    @staticmethod
    def _cx_parse_copilot(text):
        """Pull the three sections out of the reply; fall back to raw text."""
        summary_match = re.search(r'SUMMARY:\s*(.+?)(?=\n[A-Z_]+:|\Z)', text, re.DOTALL)
        sentiment_match = re.search(r'SENTIMENT:\s*(\w+)', text)
        reply_match = re.search(r'SUGGESTED_REPLY:\s*(.+)', text, re.DOTALL)

        if not (summary_match or sentiment_match or reply_match):
            return (text.strip() or False), False, False

        summary = summary_match.group(1).strip() if summary_match else False
        suggested_reply = reply_match.group(1).strip() if reply_match else False
        sentiment = False
        if sentiment_match:
            candidate = sentiment_match.group(1).strip().lower()
            if candidate in _SENTIMENT_VALUES:
                sentiment = candidate
        return summary, sentiment, suggested_reply
