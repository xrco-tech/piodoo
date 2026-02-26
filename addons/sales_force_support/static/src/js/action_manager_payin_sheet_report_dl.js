/** @odoo-module */

import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";

async function _executePayInSheetEnquiryReportDownloadAction({ env, action }) {
    console.log("action", action);
    console.log("env", env);
    
    
    env.services.ui.block();
    const url = "/payin_sheet_reports";
    const data = action.data;

    try {
        await download({ url, data });
        env.services.action.doAction({type: 'ir.actions.act_window_close'});
    } catch (e) {
        throw e;
    } finally {
        env.services.ui.unblock();
    }
}

registry
    .category("action_handlers")
    .add('ir_actions_payin_sheet_report_download', _executePayInSheetEnquiryReportDownloadAction);
