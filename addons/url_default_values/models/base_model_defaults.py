import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

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
        model_name = self._name

        # Log context keys related to URL defaults
        url_defaults = ctx.get('url_defaults', {})
        params = ctx.get('params', {})
        has_url_defaults = bool(url_defaults and isinstance(url_defaults, dict))
        has_params = bool(params and isinstance(params, dict))
        
        if has_url_defaults or has_params:
            _logger.info(
                '[url_default_values] default_get called for model=%s, fields_list=%s',
                model_name, fields_list
            )
            _logger.info(
                '[url_default_values] Context contains: url_defaults=%s, params=%s',
                url_defaults, params
            )
            # Log all default_* keys in context
            default_keys = {k: v for k, v in ctx.items() if k.startswith('default_')}
            if default_keys:
                _logger.info('[url_default_values] Context default_* keys: %s', default_keys)

        # Primary mechanism: JS passes {field: value} under 'url_defaults'
        if url_defaults and isinstance(url_defaults, dict):
            applied_defaults = {}
            for field, value in url_defaults.items():
                if field in fields_list:
                    original_value = value
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
                    applied_defaults[field] = {'original': original_value, 'coerced': value}
            
            if applied_defaults:
                _logger.info(
                    '[url_default_values] Applied url_defaults to %s: %s',
                    model_name, applied_defaults
                )

        # Secondary/legacy mechanism: raw params dict (backwards compat)
        if params and isinstance(params, dict):
            applied_params = {}
            for key, value in params.items():
                if key not in _ODOO_RESERVED_PARAMS and key in fields_list:
                    if key not in res:  # don't override url_defaults
                        original_value = value
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
                        applied_params[key] = {'original': original_value, 'coerced': value}
            
            if applied_params:
                _logger.info(
                    '[url_default_values] Applied params to %s: %s',
                    model_name, applied_params
                )

        if has_url_defaults or has_params:
            _logger.info(
                '[url_default_values] Final default_get result for %s: %s',
                model_name, res
            )

        return res
