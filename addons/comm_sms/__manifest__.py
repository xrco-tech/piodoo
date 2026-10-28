{
    'name': 'SMS Integration (Infobip, Africa\'s Talking, Connect Mobile)',
    'version': '1.1.0',
    'category': 'Discuss',
    'summary': 'Send and receive SMS through Infobip, Africa\'s Talking or Connect Mobile, per SMS account',
    'description': """
    """,
    'author': 'If I Could Code (Org)',
    'depends': ['base', 'sms'],
    'data': [
        "security/ir.model.access.csv",
        "views/sms_account_views.xml",
        "views/res_config_settings.xml",
        "data/data.xml",
    ],
    'installable': True,
    'auto_install': False,
    'license': 'OEEL-1',
}