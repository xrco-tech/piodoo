# -*- coding: utf-8 -*-
{
    'name': 'Contact Centre Workspace',
    'version': '18.0.3.3.0',
    'category': 'Communications',
    'summary': 'The Contact Centre inbox as a Discuss-style workspace: rail, list, thread, information card',
    'description': """
One screen for Contact Centre agents, laid out like the Chat2Work workspace.

* A rail on the left (Inbox, My queue, Team queues, Calls, Contacts,
  Campaigns, Templates, Sidekick).
  Each is a section of this screen.
* My queue: the calls an agent has to make, in the order they are due:
  callbacks people asked for (Chat2Work's too, when it is installed),
  dialler campaign calls, missed calls and follow-ups the agent set. The
  agent chooses a WhatsApp call or a phone call, then says how it went.
* Team queues (managers): everyone's queues, and assigning or moving calls.
  A dialler campaign says who gets its calls (shared out automatically, a
  shared pool, or by hand) and which agents; calls outside a campaign follow
  one setting on that screen.
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

The Dashboard menu shows what needs someone now (unread conversations, missed
calls, calls with no outcome, messages that did not send) and how the period
went: messages and calls, reply times, call outcomes, campaigns and the
busiest hours, with any custom dashboard cards below. The app's menus are
Workspace, Dashboard and Configuration; the older screens are under
Configuration.

The old Inbox stays, under Configuration. Sending still goes through the Contact
Centre Inbox's own methods, so the two screens behave the same.
""",
    'author': 'Tsela NavTech',
    'license': 'LGPL-3',
    'depends': ['contact_centre_inbox', 'contact_centre_sync', 'comm_dialer'],
    'data': [
        'security/ir.model.access.csv',
        'data/contact_centre_queue_data.xml',
        'views/contact_centre_workspace_views.xml',
        'views/contact_centre_queue_views.xml',
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
            'contact_centre_workspace/static/src/workspace/queue.js',
            'contact_centre_workspace/static/src/workspace/queue.xml',
            'contact_centre_workspace/static/src/workspace/team.js',
            'contact_centre_workspace/static/src/workspace/team.xml',
            'contact_centre_workspace/static/src/workspace/markdown.js',
            'contact_centre_workspace/static/src/workspace/ai_ops.js',
            'contact_centre_workspace/static/src/workspace/ai_ops.xml',
            'contact_centre_workspace/static/src/workspace/workspace.js',
            'contact_centre_workspace/static/src/workspace/workspace.xml',
            'contact_centre_workspace/static/src/dashboard/dashboard.scss',
            'contact_centre_workspace/static/src/dashboard/dashboard.js',
            'contact_centre_workspace/static/src/dashboard/dashboard.xml',
        ],
        'web.assets_web_dark': [
            'contact_centre_workspace/static/src/workspace/workspace.dark.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
