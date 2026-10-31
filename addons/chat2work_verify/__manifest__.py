# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work ID Checks',
    'version': '18.0.1.0.1',
    'category': 'Human Resources/Recruitment',
    'summary': 'Check candidates against Home Affairs through VerifyNow, and track credits',
    'description': """
Runs VerifyNow's SA ID Verification for a candidate from their encrypted ID
number, keeps only the identity fields returned, and tracks credits used and
remaining. Starts in sandbox mode, which uses mock data and no credits. More
VerifyNow services can be added to the service list later.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['chat2work'],
    'data': [
        'security/chat2work_verify_security.xml',
        'security/ir.model.access.csv',
        'data/chat2work_verify_data.xml',
        'views/chat2work_verify_views.xml',
    ],
    'installable': True,
}
