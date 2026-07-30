{
    'name': 'Kiosk Receipt Dispatch',
    'version': '1.0.0',
    'summary': 'HTTP endpoint that sends POS kiosk receipts via WhatsApp, SMS or Email',
    'description': """
        A thin, token-guarded HTTP endpoint (/receipt/send) the kiosk payment
        backend calls to dispatch a receipt through the existing comms stack:
        WhatsApp (approved template), SMS (Infobip via comm_sms), or Email
        (mail.mail). No new sending logic -- it reuses the comm_* models.
    """,
    'author': 'XRCO',
    'license': 'LGPL-3',
    'category': 'Tools',
    'depends': ['contacts', 'mail', 'comm_sms', 'comm_whatsapp'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'application': False,
    'installable': True,
}
