# -*- coding: utf-8 -*-
{
    "name": "Contact Centre AI Copilot Ops",
    "version": "18.0.1.0.0",
    "category": "Communications",
    "summary": "Chat with an AI that can create/update campaigns via tool-calling",
    "description": """
An AI Copilot chat: ask it in plain language to draft or update
contact.centre.campaign records. Uses Anthropic's tool-use API (plain
requests.post, no SDK dependency) with a small hand-written tool registry.
Chat history and an "Actions Taken" audit log are browsable in a 3-pane
view, same pattern as the Inbox.

Tools only ever create/edit DRAFT campaigns - a human must still click
"Start" on the campaign form for anything to actually send. Tool calls run
as the calling user (no sudo), so existing campaign ACLs apply normally.
""",
    "author": "Tsela NavTech",
    "license": "LGPL-3",
    "depends": ["contact_centre"],
    "data": [
        "security/ir.model.access.csv",
        "views/contact_centre_ai_ops_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "contact_centre_ai_ops/static/src/ai_ops/ai_ops.xml",
            "contact_centre_ai_ops/static/src/ai_ops/ai_ops.js",
            "contact_centre_ai_ops/static/src/ai_ops/ai_ops.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
