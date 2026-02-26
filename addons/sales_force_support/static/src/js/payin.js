/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

class PayinSheetLineOne2Many extends Many2OneField {
    async _saveLine(recordID) {
        await super._saveLine(recordID);
        if (this.props.model === "bb.payin.sheet") {
            const parentRecord = this.props.record;
            if (parentRecord) {
                await parentRecord.save({ reload: true, stayInEdit: true });
                this.trigger("reload");
            }
        }
    }
}

registry.category("fields").add("payin_sheet_line_one2many", PayinSheetLineOne2Many);