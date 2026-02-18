{
    'name': 'InfoBip SMS Integration',
    'version': '1.0.0',
    'category': 'Discuss',
    'summary': 'Add custom SMS functionality using InfoBip (SMS Service Provider) API',
    'description': """
    """,
    'author': 'If I Could Code (Org)',
    'depends': ['base', 'sms'],
    'data': [],
     "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings.xml",
        "data/data.xml",
    ],
    'installable': True,
    'auto_install': False,
    'license': 'OEEL-1',
}