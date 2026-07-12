# -*- coding: utf-8 -*-

import logging
import re

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"
BATCH_SIZE = 20
CANDIDATE_LIMIT = 100
TRANSCRIPT_MESSAGE_LIMIT = 20

_SENTIMENT_VALUES = {'positive', 'neutral', 'negative'}


class ContactCentreContact(models.Model):
    _inherit = 'contact.centre.contact'

    ai_summary = fields.Text('AI Summary')
    ai_sentiment = fields.Selection([
        ('positive', 'Positive'),
        ('neutral', 'Neutral'),
        ('negative', 'Negative'),
    ], 'AI Sentiment')
    ai_suggested_reply = fields.Text('AI Suggested Reply')
    ai_analyzed_date = fields.Datetime('AI Last Analyzed')

    # -------------------------------------------------------------------------
    # Cron entry point
    # -------------------------------------------------------------------------

    @api.model
    def _cron_process_ai_copilot(self):
        """Scheduled action: refresh AI summary/sentiment/suggested-reply
        for contacts with activity since their last analysis."""
        candidates = self.search([
            ('last_contact_date', '!=', False),
        ], order='last_contact_date desc', limit=CANDIDATE_LIMIT)

        processed = 0
        for contact in candidates:
            if processed >= BATCH_SIZE:
                break
            if contact.ai_analyzed_date and contact.ai_analyzed_date >= contact.last_contact_date:
                continue
            try:
                contact.sudo()._generate_ai_copilot()
            except Exception as e:
                _logger.error(
                    "AI Copilot: failed to analyze contact %s (%s): %s",
                    contact.name, contact.id, e, exc_info=True,
                )
            processed += 1

    def action_regenerate_ai_copilot(self):
        """Public wrapper so the form button can trigger it (Odoo blocks
        buttons from calling underscore-prefixed/private methods)."""
        for contact in self:
            contact._generate_ai_copilot()

    # -------------------------------------------------------------------------
    # Per-contact worker
    # -------------------------------------------------------------------------

    def _generate_ai_copilot(self):
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('whatsapp.anthropic_api_key')
        if not api_key:
            return

        messages = self.centre_message_ids[:TRANSCRIPT_MESSAGE_LIMIT]
        if not messages:
            return

        transcript = "\n".join(
            f"{'Customer' if m.direction == 'inbound' else 'Agent'}: {m.body_text or ''}"
            for m in reversed(messages)
        )

        prompt = (
            "You are a contact-centre copilot. Given this conversation transcript, "
            "respond with exactly three sections, each on its own line:\n"
            "SUMMARY: one or two sentence summary of the conversation\n"
            "SENTIMENT: positive, neutral, or negative\n"
            "SUGGESTED_REPLY: a suggested next reply for the agent to send\n\n"
            f"Transcript:\n{transcript}"
        )

        headers = {
            'x-api-key': api_key,
            'anthropic-version': ANTHROPIC_VERSION,
            'content-type': 'application/json',
        }
        payload = {
            'model': ANTHROPIC_MODEL,
            'max_tokens': 512,
            'messages': [{'role': 'user', 'content': prompt}],
        }

        try:
            response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=30)
        except Exception as e:
            _logger.error("AI Copilot: request error for contact %s: %s", self.id, e, exc_info=True)
            return

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            _logger.error(
                "AI Copilot: API error for contact %s: %s - %s",
                self.id, response.status_code,
                error_data.get('error', {}).get('message', response.text),
            )
            return

        content = response.json().get('content', [])
        text = content[0].get('text', '') if content else ''
        summary, sentiment, suggested_reply = self._parse_ai_response(text)

        self.write({
            'ai_summary': summary,
            'ai_sentiment': sentiment,
            'ai_suggested_reply': suggested_reply,
            'ai_analyzed_date': fields.Datetime.now(),
        })

    @staticmethod
    def _parse_ai_response(text):
        """Defensively parse the SUMMARY/SENTIMENT/SUGGESTED_REPLY sections
        out of the model's reply. Falls back to storing the raw text as the
        summary if the expected format isn't found."""
        summary_match = re.search(r'SUMMARY:\s*(.+?)(?=\n[A-Z_]+:|\Z)', text, re.DOTALL)
        sentiment_match = re.search(r'SENTIMENT:\s*(\w+)', text)
        reply_match = re.search(r'SUGGESTED_REPLY:\s*(.+)', text, re.DOTALL)

        if not (summary_match or sentiment_match or reply_match):
            return text.strip() or False, False, False

        summary = summary_match.group(1).strip() if summary_match else False
        suggested_reply = reply_match.group(1).strip() if reply_match else False

        sentiment = False
        if sentiment_match:
            candidate = sentiment_match.group(1).strip().lower()
            if candidate in _SENTIMENT_VALUES:
                sentiment = candidate

        return summary, sentiment, suggested_reply
