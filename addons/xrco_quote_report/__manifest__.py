# -*- coding: utf-8 -*-
{
    'name': 'XR Co. Quote Design',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Quotes and pro-forma invoices in the same design as our invoices',
    'description': """
Replaces the standard quotation PDF with the layout our invoices use: blue
title and total, client and provider blocks, the same line table and margins.
The invoice design itself was edited in the database (account.report_invoice_document);
this module copies its styling rather than depending on it.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['sale'],
    'data': [
        'report/quote_report.xml',
    ],
    'installable': True,
}
