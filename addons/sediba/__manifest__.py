# -*- coding: utf-8 -*-
{
    'name': 'Sediba',
    'version': '18.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Research and learnings in one place: topics, findings with their sources, and the runs that gathered them',
    'description': """
Sediba
======
Sediba (Sesotho and Setswana for a well or spring) keeps research in one
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

Nothing here sends messages or keeps a discussion thread, so an automated
user with no email address can write findings.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/sediba_security.xml',
        'security/ir.model.access.csv',
        'views/sediba_views.xml',
    ],
    'application': True,
    'installable': True,
}
