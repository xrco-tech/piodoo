# -*- coding: utf-8 -*-
{
    'name': 'Library',
    'version': '18.0.1.9.3',
    'category': 'Productivity',
    'summary': 'What we know in one place: our own company docs, and research with its sources',
    'description': """
Library
======
The Library keeps research in one
place, with what is proven kept apart from what is only a lead.

- Topics: what is being researched, what is known so far, when it was last
  looked at and when it is due again.
- Findings: one claim each, as a lead, verified, or could not confirm. Every
  finding lists its sources: what each one says, the date of the figure and
  what kind of source it is.
- A finding can only be marked verified when it has a source that is the
  organisation's own page or an official document, or two independent news
  reports, each opened and read. Sponsored content and social posts do not
  count.
- Runs: one line for each research run, by a person or a scheduled agent:
  the topic, what changed and what failed to load.
- To review: findings a person should decide on, for example when sources
  disagree.
- Workspace: the topics down the side and one page beside them: an overview,
  a topic with its findings on a board, and a finding with its sources and
  properties. Changing a record opens that record's own form.
- Company docs: what we write ourselves (About us, How we work, an FAQ),
  kept apart from research. A doc has no sources and no "verified": it has
  an owner, it is a draft until a writer publishes it, every published
  version is kept, and it carries a date to read it again. Pages sit one
  level under a doc.
- Visual blocks: a finding can carry its figures, dates and tags, and a
  topic's "What we know" then also shows as headline numbers, comparison
  bars, dates to know and organisation cards with logos. Only verified
  findings are drawn, every block opens its finding, and the same facts
  stay readable as text. A company doc can show any of these blocks.
- Other apps can show the same screen as their Reference: the published
  company docs and the verified findings marked as shown in them, read-only.
  A reader can leave a note for a doc's owner.

Nothing here sends messages or keeps a discussion thread, so an automated
user with no email address can write findings.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'html_editor'],
    'data': [
        'security/sediba_security.xml',
        'security/ir.model.access.csv',
        'views/sediba_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sediba/static/src/workspace/workspace.scss',
            'sediba/static/src/workspace/flow.scss',
            'sediba/static/src/workspace/flow.js',
            'sediba/static/src/workspace/flow.xml',
            'sediba/static/src/workspace/visual.scss',
            'sediba/static/src/workspace/visual.js',
            'sediba/static/src/workspace/visual.xml',
            'sediba/static/src/workspace/workspace.js',
            'sediba/static/src/workspace/workspace.xml',
        ],
        'web.assets_web_dark': [
            'sediba/static/src/workspace/workspace.dark.scss',
        ],
    },
    'application': True,
    'installable': True,
}
