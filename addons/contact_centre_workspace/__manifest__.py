# -*- coding: utf-8 -*-
{
    'name': 'Contact Centre Workspace',
    'version': '18.0.1.6.0',
    'category': 'Communications',
    'summary': 'The Contact Centre inbox as a Discuss-style workspace: rail, list, thread, information card',
    'description': """
One screen for Contact Centre agents, laid out like the Chat2Work workspace.

* A rail on the left (Inbox, Calls, Contacts, Campaigns, Templates, Sidekick).
  Each is a section of this screen.
* Calls: WhatsApp and VoIP calls in one list, newest first. One call shows
  its recording, transcript, summary, the other calls with that person, and
  its outcome; from there, call back or open the conversation.
* Contacts: the directory with search and filters. One contact shows their
  details (editable), tags, campaigns and latest activity; from there, call
  them, open the conversation, or add a new contact.
* Campaigns: the campaigns with their state. One campaign shows its numbers,
  sending progress, message, contacts and latest messages; managers start,
  finish, cancel or reset it there (with a confirmation that says what will
  be sent), and anyone can open the inbox narrowed to its contacts.
* Templates: the message templates of every channel, with where each is
  used and how often it has been sent. Managers write, correct and archive
  them there.
* Sidekick (managers, when the AI copilot addon contact_centre_ai_ops is
  installed; called AI Ops in the code): the copilot
  chats, with what the copilot did in each chat beside it. A change it made
  to a campaign, contact or template opens in that section.
* A conversation list with unread counts, the channel of the last message
  and filters by status and channel.
* One thread per contact: WhatsApp, SMS, email and calls together, with call
  recordings, transcripts and call outcomes. WhatsApp messages the bot sent
  are shown too, marked as automatic.
* An information card: status, wrap-up, the AI copilot (when installed),
  details and internal notes. During a call with a script, the script is
  followed there.

The old Inbox stays where it is. Sending still goes through the Contact
Centre Inbox's own methods, so the two screens behave the same.
""",
    'author': 'Tsela NavTech',
    'license': 'LGPL-3',
    'depends': ['contact_centre_inbox', 'contact_centre_sync'],
    'data': [
        'views/contact_centre_workspace_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'contact_centre_workspace/static/src/workspace/workspace.scss',
            'contact_centre_workspace/static/src/workspace/util.js',
            'contact_centre_workspace/static/src/workspace/calls.js',
            'contact_centre_workspace/static/src/workspace/calls.xml',
            'contact_centre_workspace/static/src/workspace/contacts.js',
            'contact_centre_workspace/static/src/workspace/contacts.xml',
            'contact_centre_workspace/static/src/workspace/campaigns.js',
            'contact_centre_workspace/static/src/workspace/campaigns.xml',
            'contact_centre_workspace/static/src/workspace/templates.js',
            'contact_centre_workspace/static/src/workspace/templates.xml',
            'contact_centre_workspace/static/src/workspace/markdown.js',
            'contact_centre_workspace/static/src/workspace/ai_ops.js',
            'contact_centre_workspace/static/src/workspace/ai_ops.xml',
            'contact_centre_workspace/static/src/workspace/workspace.js',
            'contact_centre_workspace/static/src/workspace/workspace.xml',
        ],
        'web.assets_web_dark': [
            'contact_centre_workspace/static/src/workspace/workspace.dark.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
