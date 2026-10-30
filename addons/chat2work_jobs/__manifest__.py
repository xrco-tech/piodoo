# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work Job Listings',
    'version': '18.0.1.1.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Outside job listings for Chat2Work, kept up to date and matched to candidates',
    'description': """
Job listings from outside sources, separate from the roles Chat2Work runs
itself (chat2work.job). Import a CSV, or point a source at a CSV feed. A daily
job refreshes feeds, closes expired listings and suggests candidates using
simple rules. Agents review every suggestion; nothing is sent to candidates.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['chat2work'],
    'data': [
        'security/ir.model.access.csv',
        'data/chat2work_jobs_data.xml',
        'wizards/chat2work_listing_import_views.xml',
        'views/chat2work_listing_views.xml',
    ],
    'installable': True,
}
