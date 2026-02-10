{
    'name': 'URL Default Values',
    'version': '1.0.0',
    'summary': 'Pass default field values to new records via clean URL query parameters',
    'description': """
        Allows passing default values to new record forms via URL query parameters
        using the default_ prefix convention, compatible with Odoo 17, 18, and 19.

        Usage:
            /odoo/some.model/new?default_field_name=value&default_other_field=value2

        Example:
            /odoo/whatsapp.chatbot.step/new?default_chatbot_id=1&default_parent_id=2
    """,
    'author': 'Custom',
    'category': 'Technical',
    'depends': ['web'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'url_default_values/static/src/js/url_default_values.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
