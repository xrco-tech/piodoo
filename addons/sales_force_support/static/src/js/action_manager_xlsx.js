/** @odoo-module **/
import { registry } from "@web/core/registry";
import { download } from "@web/core/network/download";

/**
 * This handler is responsible for generating XLSX reports.
 */
registry.category("ir.actions.report handlers").add("qwerty_xlsx", async function (action) {
    if (action.report_type === 'xlsx') {
        console.log("action_data", action.data);

        let options;
        try {
            options = JSON.parse(action.data.options || '{}');
        } catch (e) {
            console.error("Failed to parse options:", e);
            return { type: 'ir.actions.act_window_close' }; // Close the action on error
        }
        console.log("Parsed options:", options);

        let records = options.records || [];
        console.log("Selected Records:", records);

        if (Array.isArray(records) && records.length > 0) {
            for (let record_id of records) {
                console.log(`Loop iteration for Record ID: ${record_id}`);
                console.log(`Downloading file for Record ID: ${record_id}`);

                try {
                    await download({
                        url: '/xlsx_reports',
                        data: action.data,
                    });
                    console.log(`Download complete for Record ID: ${record_id}`);
                } catch (downloadError) {
                    console.error(`Unexpected error during download for Record ID: ${record_id}`, downloadError);
                }
            }
        } else {
            console.warn("No records selected for download.");
        }
        return { type: 'ir.actions.act_window_close' }; // Signal action completion
    }
    return Promise.resolve(); // Default for other actions
});
