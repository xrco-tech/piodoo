# -*- coding: utf-8 -*-

import json
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOOL_ITERATIONS = 5

SYSTEM_PROMPT = """You are an AI Copilot inside a contact-centre Odoo app. \
You can create and update marketing/support campaigns on the user's behalf \
using the tools provided. Campaigns you create or edit always stay in \
draft state - you cannot and must not attempt to start/launch a campaign \
or send any real messages; a human always reviews and clicks "Start" \
themselves. If a tool call fails (e.g. the user doesn't have permission, \
or an id doesn't exist), explain the failure plainly rather than retrying \
blindly. Keep replies short and practical."""

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
        Message.create({"session_id": self.id, "role": "assistant", "content": final_text})

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


class ContactCentreAiChatMessage(models.Model):
    _name = "contact.centre.ai.chat.message"
    _description = "Contact Centre AI Copilot Chat Message"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one("contact.centre.ai.chat", required=True, ondelete="cascade", index=True)
    role = fields.Selection([("user", "User"), ("assistant", "Assistant")], required=True)
    content = fields.Text(required=True)


class ContactCentreAiChatAction(models.Model):
    _name = "contact.centre.ai.chat.action"
    _description = "Contact Centre AI Copilot Action Taken"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one("contact.centre.ai.chat", required=True, ondelete="cascade", index=True)
    tool_name = fields.Char(required=True)
    tool_input = fields.Json()
    tool_result = fields.Json()
    success = fields.Boolean(default=True)
