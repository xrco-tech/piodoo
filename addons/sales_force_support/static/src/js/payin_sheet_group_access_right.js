/** @odoo-module */

import { registry } from "@web/core/registry"
import { formView } from "@web/views/form/form_view"
import { FormController } from "@web/views/form/form_controller"
import { useService } from "@web/core/utils/hooks";
const { useEffect } = owl

class PayinSheetsLineIdsDeleteController extends FormController {
    setup(){
        console.log("Payin Line Access JS CAlled!")
        super.setup()
        this.rpc = useService("rpc");

        useEffect(() => {
            this.disableForm()
        }, () => [this.model.root.data])

    }

    async disableForm() {
       
        const createButton = document.querySelectorAll('.o_list_record_remove')

        // Call the RPC to check if the user belongs to the group
        const userHasGroup = await this._checkUserGroup(); // Replace with actual group XML ID
        
        if (!userHasGroup) {
            if (createButton) createButton.forEach(e => e.classList.add("d-none"))
        } 
    }

    // Helper function to call the RPC method
    async _checkUserGroup() {
        return await this.rpc("/web/dataset/call_kw", {
            model: "res.users",
            method: "has_group",
            args: [ "sales_force_support.group_payin_admin"],
            kwargs: {},
        })
    }
}

const payinSheetLineIdsDeleteAccess = {
    ...formView,
    Controller: PayinSheetsLineIdsDeleteController,
}

registry.category("views").add("payin_sheet_line_ids_delete_access", payinSheetLineIdsDeleteAccess)
