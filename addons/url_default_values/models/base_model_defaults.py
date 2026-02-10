from odoo import api, models

# These are Odoo's own internal URL/context params that must never be
# mistaken for field default values.
_ODOO_RESERVED_PARAMS = frozenset({
    'cids', 'menu_id', 'action', 'active_id', 'active_ids',
    'active_model', 'view_type', 'debug', 'lang', 'tz',
})


class Base(models.AbstractModel):
    """
    Extends base default_get to support passing field default values
    via URL query parameters (prefixed with 'default_') in Odoo 17/18/19.

    The JS layer (url_default_values.js) reads query params from the URL
    *before* the SPA router strips them, stores them in the action context,
    and this Python layer reads them back in default_get.

    Two context keys are supported:
      - 'url_defaults'   : dict of {field: value} from ?default_field=value params
      - 'params'         : legacy dict support (for compatibility with other approaches)
    """
    _inherit = 'base'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        ctx = self._context

        # Primary mechanism: JS passes {field: value} under 'url_defaults'
        url_defaults = ctx.get('url_defaults', {})
        if url_defaults and isinstance(url_defaults, dict):
            for field, value in url_defaults.items():
                if field in fields_list:
                    # Basic type coercion: many2one fields need int IDs
                    field_def = self._fields.get(field)
                    if field_def:
                        try:
                            if field_def.type in ('many2one', 'integer'):
                                value = int(value)
                            elif field_def.type == 'float':
                                value = float(value)
                            elif field_def.type == 'boolean':
                                value = str(value).lower() in ('1', 'true', 'yes')
                        except (ValueError, TypeError):
                            pass  # leave value as-is if coercion fails
                    res[field] = value

        # Secondary/legacy mechanism: raw params dict (backwards compat)
        params = ctx.get('params', {})
        if params and isinstance(params, dict):
            for key, value in params.items():
                if key not in _ODOO_RESERVED_PARAMS and key in fields_list:
                    if key not in res:  # don't override url_defaults
                        field_def = self._fields.get(key)
                        if field_def:
                            try:
                                if field_def.type in ('many2one', 'integer'):
                                    value = int(value)
                                elif field_def.type == 'float':
                                    value = float(value)
                                elif field_def.type == 'boolean':
                                    value = str(value).lower() in ('1', 'true', 'yes')
                            except (ValueError, TypeError):
                                pass
                        res[key] = value

        return res
