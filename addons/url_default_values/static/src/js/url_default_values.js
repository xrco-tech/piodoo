/** @odoo-module **/

/**
 * URL Default Values
 *
 * Problem: Odoo 17+ uses an OWL-based SPA router that strips unknown query
 * parameters before the form view loads, so ?default_field=value never
 * reaches default_get().
 *
 * Solution: Read the query params from window.location *before* the router
 * clears them, then patch the action service so that every time an
 * ir.actions.act_window is executed with view_type=form (or a new-record
 * form), we inject the captured defaults into the action's context.
 *
 * Compatible with Odoo 17, 18, and 19.
 */

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";

// ---------------------------------------------------------------------------
// Step 1 – Capture query params immediately, before the router touches them.
// ---------------------------------------------------------------------------

/**
 * Reads all ?default_<field>=<value> params from the current URL and returns
 * them as a plain {field: value} object.
 * Also captures any ?<field>=<value> params that are NOT Odoo system params,
 * storing them separately as a legacy fallback.
 */
const ODOO_SYSTEM_PARAMS = new Set([
    'cids', 'menu_id', 'action', 'active_id', 'active_ids',
    'active_model', 'view_type', 'debug', 'lang', 'tz',
]);

function captureUrlDefaults() {
    const urlDefaults = {};
    const legacyParams = {};

    let search;
    try {
        search = new URLSearchParams(window.location.search);
    } catch {
        return { urlDefaults, legacyParams };
    }

    for (const [key, value] of search.entries()) {
        if (key.startsWith('default_')) {
            // e.g. default_chatbot_id=1  →  chatbot_id: "1"
            const field = key.slice('default_'.length);
            if (field) {
                urlDefaults[field] = value;
            }
        } else if (!ODOO_SYSTEM_PARAMS.has(key)) {
            // legacy bare params e.g. ?chatbot_id=1
            legacyParams[key] = value;
        }
    }

    return { urlDefaults, legacyParams };
}

// Capture immediately on module load – before router processes the URL.
const { urlDefaults: INITIAL_URL_DEFAULTS, legacyParams: INITIAL_LEGACY_PARAMS } =
    captureUrlDefaults();

const HAS_DEFAULTS =
    Object.keys(INITIAL_URL_DEFAULTS).length > 0 ||
    Object.keys(INITIAL_LEGACY_PARAMS).length > 0;

// Log initial capture
console.log('[url_default_values] Module loaded. URL:', window.location.href);
console.log('[url_default_values] Captured defaults:', INITIAL_URL_DEFAULTS);
console.log('[url_default_values] Captured legacy params:', INITIAL_LEGACY_PARAMS);
console.log('[url_default_values] Has defaults:', HAS_DEFAULTS);

// ---------------------------------------------------------------------------
// Step 2 – Patch the action service to inject defaults into form contexts.
// ---------------------------------------------------------------------------

if (HAS_DEFAULTS) {

    /**
     * Returns true when the action is about to open a blank new-record form.
     * Works for both explicit view_type=form and act_window actions that
     * default to a form view.
     */
    function isNewRecordAction(action, options = {}) {
        if (!action) return false;

        // Explicit new-record path  (/odoo/model/new)
        if (options.viewType === 'form' || action.view_type === 'form') {
            return true;
        }

        // act_window opening a form for a new record (no res_id)
        if (
            action.type === 'ir.actions.act_window' &&
            !action.res_id &&
            Array.isArray(action.views)
        ) {
            const types = action.views.map((v) => (Array.isArray(v) ? v[1] : v));
            if (types.includes('form')) return true;
        }

        return false;
    }

    /**
     * Merges our captured defaults into the action's context so that the
     * Python default_get() will receive them.
     */
    function injectDefaultsIntoAction(action) {
        if (!action) return action;

        const extraContext = {};

        if (Object.keys(INITIAL_URL_DEFAULTS).length) {
            // Primary: structured dict under 'url_defaults'
            extraContext.url_defaults = { ...INITIAL_URL_DEFAULTS };

            // Also spread as individual default_<field> keys – Odoo's own
            // default_get natively reads these from context too.
            for (const [field, value] of Object.entries(INITIAL_URL_DEFAULTS)) {
                extraContext[`default_${field}`] = value;
            }
        }

        if (Object.keys(INITIAL_LEGACY_PARAMS).length) {
            extraContext.params = { ...INITIAL_LEGACY_PARAMS };
        }

        console.log('[url_default_values] Injecting defaults into action:', {
            model: action.res_model || action.type,
            res_id: action.res_id,
            extraContext: extraContext,
            originalContext: action.context,
        });

        action.context = Object.assign({}, action.context || {}, extraContext);
        
        console.log('[url_default_values] Final action context:', action.context);
        return action;
    }

    // Register service that patches the action service to inject defaults.
    // The action service dependency ensures it's available when we start.
    registry.category("services").add("url_default_values", {
        dependencies: ["action"],
        async start(env, { action: actionService }) {
            console.log('[url_default_values] Service starting, patching action service');
            const originalDoAction = actionService.doAction.bind(actionService);

            patch(actionService, {
                async doAction(actionRequest, options = {}) {
                    console.log('[url_default_values] doAction called:', {
                        type: actionRequest?.type,
                        res_model: actionRequest?.res_model,
                        res_id: actionRequest?.res_id,
                        view_type: actionRequest?.view_type,
                        options_viewType: options?.viewType,
                    });

                    // Only inject for new-record form actions.
                    const isNew = isNewRecordAction(actionRequest, options);
                    console.log('[url_default_values] Is new record action:', isNew);

                    if (isNew) {
                        injectDefaultsIntoAction(actionRequest);
                    }
                    return originalDoAction(actionRequest, options);
                },
            });
            console.log('[url_default_values] Action service patched successfully');
        },
    });
}

// ---------------------------------------------------------------------------
// Step 3 – Additionally patch the router service to preserve default_ params
//           in the URL for as long as possible (Odoo 17/18 router awareness).
// ---------------------------------------------------------------------------

/**
 * For Odoo 17/18, the router parses the URL on startup. We patch the router
 * service's computeState / parseURL method so that our default_ params are
 * preserved in the route state and passed through to action loading.
 *
 * This is a best-effort enhancement; the primary mechanism above (action
 * service patch) is the reliable path.
 */
registry.category("services").add("url_defaults_router_bridge", {
    dependencies: [],
    start(env) {
        console.log('[url_default_values] Router bridge starting, HAS_DEFAULTS:', HAS_DEFAULTS);
        if (!HAS_DEFAULTS) {
            console.log('[url_default_values] No defaults found, skipping router bridge');
            return;
        }

        const router = env.services.router;
        if (!router) {
            console.log('[url_default_values] Router service not available');
            return;
        }

        console.log('[url_default_values] Router service found, injecting defaults into router state');

        // Odoo 17/18 router exposes `current` with `search` (query params).
        // Inject our defaults into the router's current state so action
        // loading picks them up.
        try {
            if (router.current) {
                const currentSearch = router.current.search || {};
                console.log('[url_default_values] Current router search before:', currentSearch);
                for (const [field, value] of Object.entries(INITIAL_URL_DEFAULTS)) {
                    currentSearch[`default_${field}`] = value;
                }
                router.current.search = currentSearch;
                console.log('[url_default_values] Current router search after:', router.current.search);
            } else {
                console.log('[url_default_values] Router.current is not available');
            }
        } catch (error) {
            console.error('[url_default_values] Error in router bridge:', error);
            // Non-fatal – primary mechanism handles this case
        }
    },
});
