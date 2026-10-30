# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work CV Templates',
    'version': '18.0.1.1.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Twelve QWeb CV designs candidates choose from on their CV page',
    'description': """
Adds a design picker to the guided form on the Chat2Work CV page (/cv/<token>).
The existing CV report renders whichever design the candidate chose. Agents can
change the design on the candidate form and rebuild the PDF.

Every design is a QWeb template fed by the same form answers, keeps its text
machine-readable for applicant tracking systems, and leaves out photos, ID
numbers and dates of birth.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['chat2work'],
    'data': [
        'security/ir.model.access.csv',
        'report/cv_sections.xml',
        'report/cv_layouts.xml',
        'data/chat2work_cv_template_data.xml',
        'views/chat2work_cv_page.xml',
        'views/chat2work_cv_template_views.xml',
    ],
    'installable': True,
}
