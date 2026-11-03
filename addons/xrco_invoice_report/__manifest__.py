# -*- coding: utf-8 -*-
{
    'name': 'XR Co. Invoice Design',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Our invoice and credit note PDF design',
    'description': """
The invoice design: blue title and total, client and provider blocks, a plain
line table and bank payment instructions, on A4 with invoice margins.
It was first made by editing account.report_invoice_document in the database
(2026-01-20); keeping it here means updating `account` no longer wipes it.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'report/invoice_report.xml',
    ],
    'installable': True,
}
