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

# Mirrors contact.centre.dashboard.card's own Selection field - the model
# enforces this too, this is just so the tool schema's enum matches.
DASHBOARD_CARD_MODELS = [
    "contact.centre.contact", "contact.centre.message", "contact.centre.campaign",
    "whatsapp.chatbot", "contact.centre.chatbot.session", "whatsapp.call.log",
]

SYSTEM_PROMPT = """You are an AI Copilot inside a contact-centre Odoo app. \
You can create and update marketing/support campaigns, create/extend \
linear (non-branching) WhatsApp chatbot flows, and create/update/delete \
custom dashboard cards, on the user's behalf using the tools provided. \
You also have read-only lookup tools (list_templates, search_contacts, \
list_campaigns, list_chatbots) - always use these to find real ids \
yourself instead of asking the user to supply an id or guessing one; \
only ask the user to choose between real options you looked up. \
Dashboard cards may only target these models: contact.centre.contact, \
contact.centre.message, contact.centre.campaign, whatsapp.chatbot, \
contact.centre.chatbot.session, whatsapp.call.log - no other model may \
be used. Campaigns and chatbot flows you create or edit always \
stay in draft state - you cannot and must not attempt to start/launch a \
campaign, publish a chatbot flow, or send any real messages; a human \
always reviews and clicks "Start"/"Publish" themselves. Chatbot flow step \
names may only contain letters, numbers, spaces, and these punctuation \
marks: - . , & / + $ ( ) ! ? : — no emoji or other characters, or the \
tool call will fail. If a tool call fails (e.g. the user doesn't have \
permission, or an id doesn't exist), explain the failure plainly rather \
than retrying blindly. Keep replies short and practical."""

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
        "description": "Search contact.centre.contact records by name or phone number to find contact_ids.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or phone number to search for"},
                "limit": {"type": "integer", "default": 20},
            },
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
            "list_templates": self._tool_list_templates,
            "search_contacts": self._tool_search_contacts,
            "list_campaigns": self._tool_list_campaigns,
            "list_chatbots": self._tool_list_chatbots,
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
        domain = []
        query = args.get("query")
        if query:
            domain = ["|", ("name", "ilike", query), ("phone_number", "ilike", query)]
        contacts = self.env["contact.centre.contact"].search(domain, limit=args.get("limit") or 20)
        return {"contacts": [
            {"id": c.id, "name": c.name, "phone_number": c.phone_number} for c in contacts
        ]}

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


class ContactCentreAiChatAction(models.Model):
    _name = "contact.centre.ai.chat.action"
    _description = "Contact Centre AI Copilot Action Taken"
    _order = "create_date asc, id asc"

    session_id = fields.Many2one("contact.centre.ai.chat", required=True, ondelete="cascade", index=True)
    tool_name = fields.Char(required=True)
    tool_input = fields.Json()
    tool_result = fields.Json()
    success = fields.Boolean(default=True)
