# -*- coding: utf-8 -*-

import json
import logging
import re

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOOL_ITERATIONS = 5

# Trailing tag the model can emit to offer quick-reply chips, e.g.
# <<suggestions>>["Yes, create it", "No template needed"]<<end>>
# Parsed out and stored separately - never shown to the user as raw text.
SUGGESTIONS_RE = re.compile(r"<<suggestions>>(\[.*?\])<<end>>", re.S)

# Mirrors contact.centre.dashboard.card's own Selection field - the model
# enforces this too, this is just so the tool schema's enum matches.
DASHBOARD_CARD_MODELS = [
    "contact.centre.contact", "contact.centre.message", "contact.centre.campaign",
    "whatsapp.chatbot", "contact.centre.chatbot.session", "whatsapp.call.log",
]

SYSTEM_PROMPT = """You are an AI Copilot inside a contact-centre Odoo app. \
You can create and update marketing/support campaigns, create/extend \
linear (non-branching) WhatsApp chatbot flows, create/update contacts \
and message templates, create/update native WhatsApp Business templates, \
create/update WhatsApp call teams and inbound call-routing rules, and \
create/update/delete custom dashboard cards, on the user's behalf using \
the tools provided. contact.centre.template (list_templates/create_template) \
and whatsapp.template (list_whatsapp_templates/create_whatsapp_template) \
are two different, unrelated things - the former is a plain-text note \
stored only in this app, the latter is a real Meta-approved WhatsApp \
Business template; if the user just says "template" without specifying, \
ask which one they mean rather than guessing. Templates you create via \
create_whatsapp_template are saved locally only (status stays PENDING \
without ever reaching Meta) - you cannot and must not submit a template \
to Meta for approval; a human always does that explicitly in the UI. \
Once a template has actually been submitted to Meta, update_whatsapp_template \
will refuse to touch it - tell the user to create a new template instead \
of trying to work around that. Every tool runs with the \
permissions of the person chatting with you, not an administrator - if \
a tool fails with a permission/access error, that means this user \
genuinely doesn't have that access in Odoo; tell them plainly rather \
than implying it's a bug, and don't suggest workarounds to bypass it. \
You also have read-only lookup tools (list_templates, list_whatsapp_templates, \
search_contacts, list_contact_categories, list_campaigns, list_chatbots, \
list_call_teams, list_call_routing_rules, list_messages, list_call_logs, \
list_chatbot_sessions) - always use these to find real ids yourself \
instead of asking the user to supply an id or guessing one; only ask the \
user to choose between real options you looked up. search_contacts can \
filter by name, phone, and/or tag/category (use list_contact_categories \
first if you're not sure of the exact category name/spelling, e.g. the \
user says "vendors" but the real tag is "Vendor"). Some matching \
partners won't have a contact_id yet (contact_id comes back null) - \
that just means nobody has messaged them before, not that the search \
failed; call create_contacts_from_partners on those partner_ids to get \
real contact_ids before adding them to a campaign, and briefly tell the \
user you're doing this rather than silently creating records. Message \
history (list_messages), call logs (list_call_logs), \
and chatbot sessions (list_chatbot_sessions) are read-only audit trails \
- there are no tools to create, edit, or delete records in these, and \
there never will be; if asked, explain that conversation/call history \
can't be edited via the AI Copilot. Dashboard cards may only target \
these models: contact.centre.contact, contact.centre.message, \
contact.centre.campaign, whatsapp.chatbot, contact.centre.chatbot.session, \
whatsapp.call.log - no other model may be used. Campaigns and chatbot \
flows you create or edit always stay in draft state - you cannot and \
must not attempt to start/launch a campaign, publish a chatbot flow, or \
send any real messages; a human always reviews and clicks \
"Start"/"Publish" themselves. Chatbot flow step names may only contain \
letters, numbers, spaces, and these punctuation marks: - . , & / + $ ( ) \
! ? : — no emoji or other characters, or the tool call will fail. If a \
tool call fails (e.g. the user doesn't have permission, or an id doesn't \
exist), explain the failure plainly rather than retrying blindly. Keep \
replies short and practical.

When your reply ends on a genuine fork in the conversation - a yes/no \
confirmation, or a choice between a small number of real options you \
just looked up - end your message with a quick-reply tag so the user \
can tap instead of typing: <<suggestions>>["short option 1", "short \
option 2"]<<end>>. Rules: 2-4 options, each a few words written as \
something the user would say (e.g. "Yes, create it", not "Create it? \
Yes"), valid JSON array of strings, and this must be the very last \
thing in your message with nothing after it - it's stripped before the \
user sees it, so don't also restate the same options as a numbered list \
in your prose right above it. Only add it when there's an actual \
decision point; most replies (a status update, an error explanation, a \
tool result) don't need one - never attach it just to keep the \
conversation going."""

TOOLS = [
    {
        "name": "create_campaign",
        "description": "Create a new draft contact centre campaign.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Campaign name"},
                "campaign_type": {"type": "string", "enum": ["inbound", "outbound"]},
                "channel": {"type": "string", "enum": ["whatsapp", "sms", "email", "both"]},
                "template_id": {"type": "integer", "description": "Optional contact.centre.template id"},
                "contact_ids": {"type": "array", "items": {"type": "integer"},
                                 "description": "Optional list of contact.centre.contact ids to target"},
                "description": {"type": "string"},
            },
            "required": ["name", "campaign_type", "channel"],
        },
    },
    {
        "name": "update_campaign",
        "description": "Update an existing draft campaign's fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "integer"},
                "name": {"type": "string"},
                "template_id": {"type": "integer"},
                "contact_ids": {"type": "array", "items": {"type": "integer"}},
                "description": {"type": "string"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "list_templates",
        "description": "List available contact.centre.template records (id, name, channel) to pick a template_id from.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["whatsapp", "sms", "email"],
                            "description": "Optional filter to only this channel's templates"},
            },
        },
    },
    {
        "name": "search_contacts",
        "description": (
            "Search Odoo partners by name, phone number, and/or tag/category (e.g. 'Vendor', "
            "'Desk Manufacturers' - use list_contact_categories to find real category names). "
            "Each result includes contact_id: this is null when the partner has no "
            "contact.centre.contact record yet (common for partners never synced from a "
            "campaign/chatbot/purchase flow) - call create_contacts_from_partners on those "
            "partner_ids before adding them to a campaign, since campaigns need a contact_id, "
            "not a partner_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or phone number to search for"},
                "category": {"type": "string", "description": "Tag/category name to filter by, e.g. 'Vendor' or 'Desk Manufacturers'"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_contact_categories",
        "description": "List available partner tags/categories (e.g. Vendor, Desk Manufacturers) to use with search_contacts' category filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional name search"},
            },
        },
    },
    {
        "name": "create_contacts_from_partners",
        "description": (
            "Find-or-create contact.centre.contact records for existing Odoo partners (e.g. "
            "vendors/customers found via search_contacts whose contact_id came back null), so "
            "they can be added to a campaign's contact_ids."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "partner_ids": {"type": "array", "items": {"type": "integer"},
                                 "description": "res.partner ids, from search_contacts' partner_id field"},
            },
            "required": ["partner_ids"],
        },
    },
    {
        "name": "list_campaigns",
        "description": "List existing campaigns (id, name, state, channel) to find a campaign_id to update.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional name search"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_chatbots",
        "description": "List existing chatbot flows (id, name, channel, status) to find a chatbot_id to update.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional name search"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "create_contact",
        "description": "Create a new contact.centre.contact (finds/reuses an existing partner by phone number if one already exists).",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string", "description": "Phone number, used to find or create the underlying partner"},
                "name": {"type": "string", "description": "Optional contact name"},
                "email": {"type": "string", "description": "Optional email address"},
            },
            "required": ["phone_number"],
        },
    },
    {
        "name": "update_contact",
        "description": "Update an existing contact's name, phone number, or email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer"},
                "name": {"type": "string"},
                "phone_number": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "create_template",
        "description": "Create a new contact.centre.template message template.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "channel": {"type": "string", "enum": ["whatsapp", "sms", "email"]},
                "body_text": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["name", "channel", "body_text"],
        },
    },
    {
        "name": "update_template",
        "description": "Update an existing message template's fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "template_id": {"type": "integer"},
                "name": {"type": "string"},
                "channel": {"type": "string", "enum": ["whatsapp", "sms", "email"]},
                "body_text": {"type": "string"},
                "notes": {"type": "string"},
                "active": {"type": "boolean"},
            },
            "required": ["template_id"],
        },
    },
    {
        "name": "list_call_teams",
        "description": "List WhatsApp call teams (id, name, member_count) to find a team_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional name search"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "create_call_team",
        "description": "Create a new WhatsApp call team (a named queue of agents). Does not manage team membership.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_call_team",
        "description": "Update an existing call team's name, description, or active state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "integer"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "active": {"type": "boolean"},
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "list_call_routing_rules",
        "description": "List inbound call routing rules (id, name, sequence, caller_pattern, team names) to find a rule_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional name search"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "create_call_routing_rule",
        "description": "Create a new inbound call routing rule that sends matching calls to one or more call teams.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "team_ids": {"type": "array", "items": {"type": "integer"}, "description": "whatsapp.call.team ids, from list_call_teams"},
                "caller_pattern": {"type": "string", "description": "Optional regex on the caller's number, e.g. ^\\+27"},
                "sequence": {"type": "integer", "description": "Lower runs first; default 10"},
            },
            "required": ["name", "team_ids"],
        },
    },
    {
        "name": "update_call_routing_rule",
        "description": "Update an existing call routing rule's fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer"},
                "name": {"type": "string"},
                "team_ids": {"type": "array", "items": {"type": "integer"}},
                "caller_pattern": {"type": "string"},
                "sequence": {"type": "integer"},
                "active": {"type": "boolean"},
            },
            "required": ["rule_id"],
        },
    },
    {
        "name": "list_messages",
        "description": "Read-only: list WhatsApp/SMS/email conversation history for a contact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer", "description": "Optional contact.centre.contact id to filter to"},
                "channel": {"type": "string", "enum": ["whatsapp", "sms", "email"]},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_call_logs",
        "description": "Read-only: list WhatsApp call history, optionally filtered by caller/callee number or contact name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional number or contact-name search"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_chatbot_sessions",
        "description": "Read-only: list contact-centre chatbot conversation sessions (state, current step) for a contact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "integer", "description": "Optional contact.centre.contact id to filter to"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_whatsapp_templates",
        "description": "List native WhatsApp Business templates (whatsapp.template - the ones Meta actually sees, not contact.centre.template) with their approval status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional name search"},
                "status": {"type": "string", "enum": ["PENDING", "APPROVED", "REJECTED", "PAUSED", "PENDING_DELETION", "DISABLED"]},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "create_whatsapp_template",
        "description": (
            "Create a new native WhatsApp Business template (whatsapp.template). This only "
            "saves it locally in PENDING status - it is NOT sent to Meta for approval. "
            "Image/video/document headers aren't supported here (they need a media handle "
            "uploaded through the UI first); only a plain TEXT header is available via this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Lowercase letters, numbers, and underscores only, e.g. order_confirmation"},
                "language": {"type": "string", "default": "en", "description": "ISO 639 language code"},
                "category": {"type": "string", "enum": ["AUTHENTICATION", "UTILITY", "MARKETING"], "default": "UTILITY"},
                "body": {"type": "string", "description": "Message body; use {{1}}, {{2}}, etc. for variables"},
                "header_text": {"type": "string", "description": "Optional plain text header"},
                "footer": {"type": "string", "description": "Optional footer, max 60 characters"},
                "buttons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "button_type": {"type": "string", "enum": ["QUICK_REPLY", "URL", "PHONE_NUMBER"]},
                            "text": {"type": "string", "description": "Max 25 characters"},
                            "url": {"type": "string", "description": "Required when button_type is URL"},
                            "phone_number": {"type": "string", "description": "Required when button_type is PHONE_NUMBER"},
                        },
                        "required": ["button_type", "text"],
                    },
                },
                "description": {"type": "string", "description": "Internal notes, not sent to Meta"},
            },
            "required": ["name", "category", "body"],
        },
    },
    {
        "name": "update_whatsapp_template",
        "description": "Update an existing whatsapp.template. Refuses to edit a template that has already been submitted to Meta (once submitted, Meta owns that template's identity) - create a new one instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "template_id": {"type": "integer"},
                "name": {"type": "string"},
                "language": {"type": "string"},
                "category": {"type": "string", "enum": ["AUTHENTICATION", "UTILITY", "MARKETING"]},
                "body": {"type": "string"},
                "header_text": {"type": "string"},
                "footer": {"type": "string"},
                "buttons": {
                    "type": "array",
                    "description": "Replaces all existing buttons on this template",
                    "items": {
                        "type": "object",
                        "properties": {
                            "button_type": {"type": "string", "enum": ["QUICK_REPLY", "URL", "PHONE_NUMBER"]},
                            "text": {"type": "string"},
                            "url": {"type": "string"},
                            "phone_number": {"type": "string"},
                        },
                        "required": ["button_type", "text"],
                    },
                },
                "description": {"type": "string"},
            },
            "required": ["template_id"],
        },
    },
    {
        "name": "create_chatbot_flow",
        "description": (
            "Create a new linear (non-branching) chatbot flow: an ordered sequence of "
            "plain-text messages sent one after another automatically when triggered. "
            "Not for flows that need to wait for customer replies or branch on answers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Chatbot flow name"},
                "channel": {"type": "string", "enum": ["whatsapp", "sms", "email", "voice"], "default": "whatsapp"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Short internal label for this step"},
                            "body": {"type": "string", "description": "The message text to send"},
                        },
                        "required": ["name", "body"],
                    },
                },
            },
            "required": ["name", "steps"],
        },
    },
    {
        "name": "update_chatbot_flow",
        "description": (
            "Rename an existing chatbot flow and/or append more message steps to the "
            "end of its linear sequence. Cannot insert, remove, or branch steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chatbot_id": {"type": "integer"},
                "name": {"type": "string"},
                "append_steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["name", "body"],
                    },
                },
            },
            "required": ["chatbot_id"],
        },
    },
    {
        "name": "create_dashboard_card",
        "description": "Add a new custom metric card to the Contact Centre dashboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Card label"},
                "model_name": {"type": "string", "enum": DASHBOARD_CARD_MODELS},
                "metric_type": {"type": "string", "enum": ["count", "group_by"], "default": "count"},
                "domain": {"type": "array", "description": "Odoo domain as a list, e.g. [[\"channel\",\"=\",\"whatsapp\"]]"},
                "group_by_field": {"type": "string", "description": "Required when metric_type is group_by"},
                "icon": {"type": "string", "description": "FontAwesome class, e.g. fa-comments"},
                "color": {"type": "string", "enum": ["primary", "info", "warning", "success", "danger"]},
            },
            "required": ["name", "model_name"],
        },
    },
    {
        "name": "update_dashboard_card",
        "description": "Update an existing custom dashboard card's fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer"},
                "name": {"type": "string"},
                "model_name": {"type": "string", "enum": DASHBOARD_CARD_MODELS},
                "metric_type": {"type": "string", "enum": ["count", "group_by"]},
                "domain": {"type": "array"},
                "group_by_field": {"type": "string"},
                "icon": {"type": "string"},
                "color": {"type": "string", "enum": ["primary", "info", "warning", "success", "danger"]},
                "active": {"type": "boolean"},
            },
            "required": ["card_id"],
        },
    },
    {
        "name": "delete_dashboard_card",
        "description": "Delete a custom dashboard card.",
        "input_schema": {
            "type": "object",
            "properties": {"card_id": {"type": "integer"}},
            "required": ["card_id"],
        },
    },
]


class ContactCentreAiChat(models.Model):
    _name = "contact.centre.ai.chat"
    _description = "Contact Centre AI Copilot Chat"
    _order = "write_date desc, id desc"

    name = fields.Char("Name", default="New Chat", required=True)
    user_id = fields.Many2one("res.users", "Started By", default=lambda self: self.env.user, required=True)
    message_ids = fields.One2many("contact.centre.ai.chat.message", "session_id", "Messages")
    action_ids = fields.One2many("contact.centre.ai.chat.action", "session_id", "Actions Taken")

    # -------------------------------------------------------------------------
    # Orchestration
    # -------------------------------------------------------------------------

    def send_message(self, text):
        self.ensure_one()
        Message = self.env["contact.centre.ai.chat.message"]
        Message.create({"session_id": self.id, "role": "user", "content": text})

        api_key = self.env["ir.config_parameter"].sudo().get_param("whatsapp.anthropic_api_key")
        if not api_key:
            Message.create({
                "session_id": self.id, "role": "assistant",
                "content": "The Anthropic API key isn't configured yet (Contact Centre > "
                           "Configuration > WhatsApp > Settings > AI Agent).",
            })
            return

        messages = [{"role": m.role, "content": m.content} for m in self.message_ids]
        final_text = self._run_tool_loop(api_key, messages)
        clean_text, suggestions = self._extract_suggestions(final_text)
        Message.create({
            "session_id": self.id, "role": "assistant",
            "content": clean_text, "suggestions": suggestions,
        })

    def _extract_suggestions(self, text):
        """Split a trailing <<suggestions>>[...]<<end>> tag off the model's
        reply. Always strips the tag from the visible text even if the JSON
        inside turns out malformed, so a formatting slip never leaks raw
        markup into the chat."""
        match = SUGGESTIONS_RE.search(text or "")
        if not match:
            return text, None
        clean_text = (text[:match.start()] + text[match.end():]).strip()
        try:
            suggestions = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return clean_text, None
        if not isinstance(suggestions, list):
            return clean_text, None
        suggestions = [s.strip() for s in suggestions if isinstance(s, str) and s.strip()][:4]
        return clean_text, suggestions or None

    def _run_tool_loop(self, api_key, messages):
        self.ensure_one()
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        for _iteration in range(MAX_TOOL_ITERATIONS):
            payload = {
                "model": ANTHROPIC_MODEL,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "messages": messages,
                "tools": TOOLS,
            }
            try:
                response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=30)
            except Exception as e:
                _logger.error("AI Ops: request error for session %s: %s", self.id, e, exc_info=True)
                return "Sorry, something went wrong talking to the AI."

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                _logger.error(
                    "AI Ops: API error for session %s: %s - %s",
                    self.id, response.status_code,
                    error_data.get("error", {}).get("message", response.text),
                )
                return "Sorry, the AI request failed."

            data = response.json()
            content = data.get("content", [])
            tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]

            if not tool_use_blocks:
                return "".join(b.get("text", "") for b in content if b.get("type") == "text")

            messages.append({"role": "assistant", "content": content})
            tool_results = []
            for block in tool_use_blocks:
                result = self._execute_tool(block.get("name"), block.get("input") or {})
                self.env["contact.centre.ai.chat.action"].create({
                    "session_id": self.id,
                    "tool_name": block.get("name"),
                    "tool_input": block.get("input") or {},
                    "tool_result": result,
                    "success": "error" not in result,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": json.dumps(result),
                })
            messages.append({"role": "user", "content": tool_results})

        return "Sorry, I wasn't able to finish that within the allowed steps."

    def _execute_tool(self, name, args):
        self.ensure_one()
        handlers = {
            "create_campaign": self._tool_create_campaign,
            "update_campaign": self._tool_update_campaign,
            "list_templates": self._tool_list_templates,
            "search_contacts": self._tool_search_contacts,
            "list_contact_categories": self._tool_list_contact_categories,
            "create_contacts_from_partners": self._tool_create_contacts_from_partners,
            "list_campaigns": self._tool_list_campaigns,
            "list_chatbots": self._tool_list_chatbots,
            "create_contact": self._tool_create_contact,
            "update_contact": self._tool_update_contact,
            "create_template": self._tool_create_template,
            "update_template": self._tool_update_template,
            "list_call_teams": self._tool_list_call_teams,
            "create_call_team": self._tool_create_call_team,
            "update_call_team": self._tool_update_call_team,
            "list_call_routing_rules": self._tool_list_call_routing_rules,
            "create_call_routing_rule": self._tool_create_call_routing_rule,
            "update_call_routing_rule": self._tool_update_call_routing_rule,
            "list_messages": self._tool_list_messages,
            "list_call_logs": self._tool_list_call_logs,
            "list_chatbot_sessions": self._tool_list_chatbot_sessions,
            "list_whatsapp_templates": self._tool_list_whatsapp_templates,
            "create_whatsapp_template": self._tool_create_whatsapp_template,
            "update_whatsapp_template": self._tool_update_whatsapp_template,
            "create_chatbot_flow": self._tool_create_chatbot_flow,
            "update_chatbot_flow": self._tool_update_chatbot_flow,
            "create_dashboard_card": self._tool_create_dashboard_card,
            "update_dashboard_card": self._tool_update_dashboard_card,
            "delete_dashboard_card": self._tool_delete_dashboard_card,
        }
        handler = handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        try:
            return handler(args)
        except Exception as e:
            _logger.warning("AI Ops: tool %s failed for session %s: %s", name, self.id, e)
            return {"error": str(e)}

    # -------------------------------------------------------------------------
    # Tools — no sudo(): run as the calling user, existing ACLs apply as-is.
    # Campaigns always land in 'draft' - create()/write() never start one.
    # -------------------------------------------------------------------------

    def _tool_create_campaign(self, args):
        vals = {
            "name": args["name"],
            "campaign_type": args["campaign_type"],
            "channel": args["channel"],
        }
        if args.get("template_id"):
            vals["template_id"] = args["template_id"]
        if args.get("contact_ids"):
            vals["contact_ids"] = [(6, 0, args["contact_ids"])]
        if args.get("description"):
            vals["description"] = args["description"]
        campaign = self.env["contact.centre.campaign"].create(vals)
        return {"campaign_id": campaign.id, "name": campaign.name, "state": campaign.state}

    def _tool_update_campaign(self, args):
        campaign = self.env["contact.centre.campaign"].browse(args["campaign_id"])
        if not campaign.exists():
            return {"error": f"Campaign {args['campaign_id']} not found"}
        vals = {}
        if "name" in args:
            vals["name"] = args["name"]
        if "template_id" in args:
            vals["template_id"] = args["template_id"]
        if "contact_ids" in args:
            vals["contact_ids"] = [(6, 0, args["contact_ids"])]
        if "description" in args:
            vals["description"] = args["description"]
        campaign.write(vals)
        return {"campaign_id": campaign.id, "updated_fields": list(vals.keys())}

    def _tool_list_templates(self, args):
        domain = [("channel", "=", args["channel"])] if args.get("channel") else []
        templates = self.env["contact.centre.template"].search(domain, limit=50)
        return {"templates": [
            {"id": t.id, "name": t.name, "channel": t.channel} for t in templates
        ]}

    def _tool_search_contacts(self, args):
        Partner = self.env["res.partner"]
        domain = []
        query = args.get("query")
        category = args.get("category")
        if query:
            domain += ["|", "|", ("name", "ilike", query), ("phone", "ilike", query), ("mobile", "ilike", query)]
        if category:
            domain.append(("category_id.name", "ilike", category))
        partners = Partner.search(domain, limit=args.get("limit") or 20)
        contacts_by_partner = {
            c.partner_id.id: c.id
            for c in self.env["contact.centre.contact"].search([("partner_id", "in", partners.ids)])
        }
        return {"contacts": [
            {
                "partner_id": p.id,
                "contact_id": contacts_by_partner.get(p.id),
                "name": p.name,
                "phone_number": p.mobile or p.phone,
                "categories": p.category_id.mapped("name"),
            }
            for p in partners
        ]}

    def _tool_list_contact_categories(self, args):
        domain = [("name", "ilike", args["query"])] if args.get("query") else []
        categories = self.env["res.partner.category"].search(domain, limit=50)
        return {"categories": [{"id": c.id, "name": c.name} for c in categories]}

    def _tool_create_contacts_from_partners(self, args):
        partner_ids = args["partner_ids"]
        Partner = self.env["res.partner"].browse(partner_ids)
        missing = set(partner_ids) - set(Partner.exists().ids)
        if missing:
            return {"error": f"Partner ids not found: {sorted(missing)}"}
        Contact = self.env["contact.centre.contact"]
        results = []
        for partner in Partner:
            contact = Contact.search([("partner_id", "=", partner.id)], limit=1)
            if not contact:
                contact = Contact.create({"partner_id": partner.id})
            results.append({"partner_id": partner.id, "contact_id": contact.id, "name": contact.name})
        return {"contacts": results}

    def _tool_list_campaigns(self, args):
        domain = [("name", "ilike", args["query"])] if args.get("query") else []
        campaigns = self.env["contact.centre.campaign"].search(domain, limit=args.get("limit") or 20)
        return {"campaigns": [
            {"id": c.id, "name": c.name, "state": c.state, "channel": c.channel} for c in campaigns
        ]}

    def _tool_list_chatbots(self, args):
        domain = [("name", "ilike", args["query"])] if args.get("query") else []
        chatbots = self.env["whatsapp.chatbot"].search(domain, limit=args.get("limit") or 20)
        return {"chatbots": [
            {"id": c.id, "name": c.name, "channel": c.channel, "status": c.status} for c in chatbots
        ]}

    def _tool_create_contact(self, args):
        phone = args["phone_number"]
        clean = re.sub(r"\D", "", phone or "")
        Partner = self.env["res.partner"]
        partner = Partner.browse()
        if clean:
            partner = Partner.search(
                ["|", ("phone", "ilike", clean), ("mobile", "ilike", clean)], limit=1)
        if not partner:
            partner = Partner.create({
                "name": args.get("name") or phone,
                "mobile": phone,
                "is_company": False,
            })
        else:
            partner_vals = {}
            if args.get("name"):
                partner_vals["name"] = args["name"]
            if partner_vals:
                partner.write(partner_vals)
        if args.get("email"):
            partner.write({"email": args["email"]})
        contact = self.env["contact.centre.contact"].search([("partner_id", "=", partner.id)], limit=1)
        if not contact:
            contact = self.env["contact.centre.contact"].create({"partner_id": partner.id})
        return {"contact_id": contact.id, "name": contact.name, "phone_number": contact.phone_number}

    def _tool_update_contact(self, args):
        contact = self.env["contact.centre.contact"].browse(args["contact_id"])
        if not contact.exists():
            return {"error": f"Contact {args['contact_id']} not found"}
        vals = {}
        for key in ("name", "phone_number", "email"):
            if key in args:
                vals[key] = args[key]
        contact.write(vals)
        return {"contact_id": contact.id, "updated_fields": list(vals.keys())}

    def _tool_create_template(self, args):
        vals = {
            "name": args["name"],
            "channel": args["channel"],
            "body_text": args["body_text"],
        }
        if args.get("notes"):
            vals["notes"] = args["notes"]
        template = self.env["contact.centre.template"].create(vals)
        return {"template_id": template.id, "name": template.name}

    def _tool_update_template(self, args):
        template = self.env["contact.centre.template"].browse(args["template_id"])
        if not template.exists():
            return {"error": f"Template {args['template_id']} not found"}
        vals = {}
        for key in ("name", "channel", "body_text", "notes", "active"):
            if key in args:
                vals[key] = args[key]
        template.write(vals)
        return {"template_id": template.id, "updated_fields": list(vals.keys())}

    def _tool_list_call_teams(self, args):
        domain = [("name", "ilike", args["query"])] if args.get("query") else []
        teams = self.env["whatsapp.call.team"].search(domain, limit=args.get("limit") or 20)
        return {"teams": [
            {"id": t.id, "name": t.name, "active": t.active, "member_count": t.member_count} for t in teams
        ]}

    def _tool_create_call_team(self, args):
        vals = {"name": args["name"]}
        if args.get("description"):
            vals["description"] = args["description"]
        team = self.env["whatsapp.call.team"].create(vals)
        return {"team_id": team.id, "name": team.name}

    def _tool_update_call_team(self, args):
        team = self.env["whatsapp.call.team"].browse(args["team_id"])
        if not team.exists():
            return {"error": f"Call team {args['team_id']} not found"}
        vals = {}
        for key in ("name", "description", "active"):
            if key in args:
                vals[key] = args[key]
        team.write(vals)
        return {"team_id": team.id, "updated_fields": list(vals.keys())}

    def _tool_list_call_routing_rules(self, args):
        domain = [("name", "ilike", args["query"])] if args.get("query") else []
        rules = self.env["whatsapp.call.routing.rule"].search(domain, limit=args.get("limit") or 20)
        return {"rules": [
            {"id": r.id, "name": r.name, "sequence": r.sequence, "active": r.active,
             "caller_pattern": r.caller_pattern, "team_ids": r.team_ids.ids,
             "team_names": r.team_ids.mapped("name")} for r in rules
        ]}

    def _tool_create_call_routing_rule(self, args):
        vals = {
            "name": args["name"],
            "team_ids": [(6, 0, args["team_ids"])],
        }
        if args.get("caller_pattern"):
            vals["caller_pattern"] = args["caller_pattern"]
        if args.get("sequence") is not None:
            vals["sequence"] = args["sequence"]
        rule = self.env["whatsapp.call.routing.rule"].create(vals)
        return {"rule_id": rule.id, "name": rule.name}

    def _tool_update_call_routing_rule(self, args):
        rule = self.env["whatsapp.call.routing.rule"].browse(args["rule_id"])
        if not rule.exists():
            return {"error": f"Routing rule {args['rule_id']} not found"}
        vals = {}
        if "name" in args:
            vals["name"] = args["name"]
        if "team_ids" in args:
            vals["team_ids"] = [(6, 0, args["team_ids"])]
        if "caller_pattern" in args:
            vals["caller_pattern"] = args["caller_pattern"]
        if "sequence" in args:
            vals["sequence"] = args["sequence"]
        if "active" in args:
            vals["active"] = args["active"]
        rule.write(vals)
        return {"rule_id": rule.id, "updated_fields": list(vals.keys())}

    def _tool_list_messages(self, args):
        domain = []
        if args.get("contact_id"):
            domain.append(("contact_id", "=", args["contact_id"]))
        if args.get("channel"):
            domain.append(("channel", "=", args["channel"]))
        messages = self.env["contact.centre.message"].search(domain, limit=args.get("limit") or 20)
        return {"messages": [
            {"id": m.id, "contact_id": m.contact_id.id, "channel": m.channel, "direction": m.direction,
             "status": m.status, "body_text": m.body_text, "message_timestamp": str(m.message_timestamp)}
            for m in messages
        ]}

    def _tool_list_call_logs(self, args):
        domain = []
        query = args.get("query")
        if query:
            domain = ["|", "|", ("from_number", "ilike", query),
                      ("to_number", "ilike", query), ("partner_id.name", "ilike", query)]
        logs = self.env["whatsapp.call.log"].search(domain, limit=args.get("limit") or 20)
        return {"call_logs": [
            {"id": c.id, "contact_display": c.contact_display, "call_direction": c.call_direction,
             "call_status": c.call_status, "duration_display": c.duration_display,
             "call_timestamp": str(c.call_timestamp)} for c in logs
        ]}

    def _tool_list_chatbot_sessions(self, args):
        domain = [("contact_id", "=", args["contact_id"])] if args.get("contact_id") else []
        sessions = self.env["contact.centre.chatbot.session"].search(
            domain, limit=args.get("limit") or 20, order="id desc")
        return {"sessions": [
            {"id": s.id, "contact_id": s.contact_id.id, "chatbot_name": s.chatbot_id.name,
             "channel": s.channel, "state": s.state,
             "current_step": s.current_step_id.name if s.current_step_id else None}
            for s in sessions
        ]}

    def _tool_list_whatsapp_templates(self, args):
        domain = []
        if args.get("query"):
            domain.append(("name", "ilike", args["query"]))
        if args.get("status"):
            domain.append(("status", "=", args["status"]))
        templates = self.env["whatsapp.template"].search(domain, limit=args.get("limit") or 20)
        return {"templates": [
            {"id": t.id, "name": t.name, "language": t.language, "category": t.category,
             "status": t.status, "submitted_to_meta": bool(t.template_id_meta)}
            for t in templates
        ]}

    def _tool_create_whatsapp_template(self, args):
        if not re.match(r"^[a-z0-9_]+$", args["name"]):
            return {"error": "Template name must be lowercase letters, numbers, and underscores only"}
        vals = {
            "name": args["name"],
            "language": args.get("language") or "en",
            "category": args["category"],
            "body": args["body"],
        }
        if args.get("header_text"):
            vals["header_type"] = "TEXT"
            vals["header_text"] = args["header_text"]
        if args.get("footer"):
            vals["footer"] = args["footer"]
        if args.get("description"):
            vals["description"] = args["description"]
        template = self.env["whatsapp.template"].create(vals)
        if args.get("buttons"):
            self._write_whatsapp_template_buttons(template, args["buttons"])
        return {"template_id": template.id, "name": template.name, "status": template.status}

    def _tool_update_whatsapp_template(self, args):
        template = self.env["whatsapp.template"].browse(args["template_id"])
        if not template.exists():
            return {"error": f"Template {args['template_id']} not found"}
        if template.template_id_meta:
            return {"error": "This template was already submitted to Meta and can't be edited here - create a new template instead"}
        if "name" in args and not re.match(r"^[a-z0-9_]+$", args["name"]):
            return {"error": "Template name must be lowercase letters, numbers, and underscores only"}
        vals = {}
        for key in ("name", "language", "category", "body", "footer", "description"):
            if key in args:
                vals[key] = args[key]
        if "header_text" in args:
            vals["header_type"] = "TEXT"
            vals["header_text"] = args["header_text"]
        if vals:
            template.write(vals)
        if "buttons" in args:
            self._write_whatsapp_template_buttons(template, args["buttons"], replace=True)
        return {"template_id": template.id, "updated_fields": list(vals.keys())}

    def _write_whatsapp_template_buttons(self, template, buttons, replace=False):
        if replace:
            template.button_ids.unlink()
        Button = self.env["whatsapp.template.button"]
        for i, b in enumerate(buttons):
            Button.create({
                "template_id": template.id,
                "sequence": (i + 1) * 10,
                "button_type": b["button_type"],
                "text": b["text"],
                "url": b.get("url"),
                "phone_number": b.get("phone_number"),
            })

    def _tool_create_chatbot_flow(self, args):
        chatbot = self.env["whatsapp.chatbot"].create({
            "name": args["name"],
            "channel": args.get("channel", "whatsapp"),
        })
        Step = self.env["whatsapp.chatbot.step"]
        parent_id = False
        step_ids = []
        for i, step_def in enumerate(args["steps"]):
            step = Step.create({
                "chatbot_id": chatbot.id,
                "name": step_def["name"],
                "step_type": "message",
                "body_plain": step_def["body"],
                "parent_id": parent_id,
                "sequence": (i + 1) * 10,
            })
            step_ids.append(step.id)
            parent_id = step.id
        return {"chatbot_id": chatbot.id, "name": chatbot.name, "status": chatbot.status, "step_ids": step_ids}

    def _tool_update_chatbot_flow(self, args):
        chatbot = self.env["whatsapp.chatbot"].browse(args["chatbot_id"])
        if not chatbot.exists():
            return {"error": f"Chatbot {args['chatbot_id']} not found"}

        vals = {}
        if "name" in args:
            vals["name"] = args["name"]
        if vals:
            chatbot.write(vals)

        added_step_ids = []
        if args.get("append_steps"):
            Step = self.env["whatsapp.chatbot.step"]
            current = Step.search(
                [("chatbot_id", "=", chatbot.id), ("parent_id", "=", False)],
                order="sequence asc", limit=1,
            )
            next_sequence = 10
            parent_id = False
            if current:
                # Flows this tool creates are always a strict single-child
                # chain, so following child_ids[0] safely finds the current end.
                while current.child_ids:
                    current = current.child_ids.sorted(key=lambda s: (s.sequence, s.id))[0]
                parent_id = current.id
                next_sequence = (current.sequence or 10) + 10
            for step_def in args["append_steps"]:
                step = Step.create({
                    "chatbot_id": chatbot.id,
                    "name": step_def["name"],
                    "step_type": "message",
                    "body_plain": step_def["body"],
                    "parent_id": parent_id,
                    "sequence": next_sequence,
                })
                added_step_ids.append(step.id)
                parent_id = step.id
                next_sequence += 10

        return {"chatbot_id": chatbot.id, "updated_fields": list(vals.keys()), "added_step_ids": added_step_ids}

    def _tool_create_dashboard_card(self, args):
        vals = {
            "name": args["name"],
            "model_name": args["model_name"],
        }
        for key in ("metric_type", "domain", "group_by_field", "icon", "color"):
            if args.get(key) is not None:
                vals[key] = args[key]
        card = self.env["contact.centre.dashboard.card"].create(vals)
        return {"card_id": card.id, "name": card.name}

    def _tool_update_dashboard_card(self, args):
        card = self.env["contact.centre.dashboard.card"].browse(args["card_id"])
        if not card.exists():
            return {"error": f"Dashboard card {args['card_id']} not found"}
        vals = {}
        for key in ("name", "model_name", "metric_type", "domain", "group_by_field", "icon", "color", "active"):
            if key in args:
                vals[key] = args[key]
        card.write(vals)
        return {"card_id": card.id, "updated_fields": list(vals.keys())}

    def _tool_delete_dashboard_card(self, args):
        card = self.env["contact.centre.dashboard.card"].browse(args["card_id"])
        if not card.exists():
            return {"error": f"Dashboard card {args['card_id']} not found"}
        name = card.name
        card.unlink()
        return {"deleted_card_id": args["card_id"], "name": name}


class ContactCentreAiChatMessage(models.Model):
    _name = "contact.centre.ai.chat.message"
    _description = "Contact Centre AI Copilot Chat Message"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one("contact.centre.ai.chat", required=True, ondelete="cascade", index=True)
    role = fields.Selection([("user", "User"), ("assistant", "Assistant")], required=True)
    content = fields.Text(required=True)
    suggestions = fields.Json()


class ContactCentreAiChatAction(models.Model):
    _name = "contact.centre.ai.chat.action"
    _description = "Contact Centre AI Copilot Action Taken"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one("contact.centre.ai.chat", required=True, ondelete="cascade", index=True)
    tool_name = fields.Char(required=True)
    tool_input = fields.Json()
    tool_result = fields.Json()
    success = fields.Boolean(default=True)
