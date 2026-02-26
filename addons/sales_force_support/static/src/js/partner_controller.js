/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { KanbanController } from "@web/views/kanban/kanban_controller";

console.log("Partner Controller JS File Loaded in Odoo 17");

// Patch for FormController
patch(FormController.prototype, {
    async openRecord(ev) {

        console.log("FormController openRecord triggered");

        if (this.model.config.resModel === "res.partner") {
            console.log("Condition True");

            console.log("FormController: res.partner condition met");
            ev?.stopPropagation?.();

            const record = this.model.root.records.find((rec) => rec.data.res_id === ev.data?.id);
            console.log("FormController Record:", record);

            if (record?.data?.view_model && record.data.view_model !== "res.partner") {
                const action = await this.env.services.orm.call(
                    record.data.view_model,
                    "get_formview_action",
                    [[record.data.view_res_id]]
                );
                return this.env.services.action.doAction(action);
            }
        }

        // Default behavior
        return super.openRecord(ev);
    }
});

// Patch for ListController
patch(ListController.prototype, {
    async openRecord(ev) {
        console.log("ListController openRecord triggered");

        if (this.model.config.resModel === "res.partner") {
            console.log("Condition True");
            console.log("ListController: res.partner condition met");
            ev?.stopPropagation?.();

            const record = this.model.root.records.find((rec) => rec.data.res_id === ev.data?.id);
            console.log("ListController Record:", record);

            if (record?.data?.view_model && record.data.view_model !== "res.partner") {
                const action = await this.env.services.orm.call(
                    record.data.view_model,
                    "get_formview_action",
                    [[record.data.view_res_id]]
                );
                return this.env.services.action.doAction(action);
            }
        }

        // Default behavior
        return super.openRecord(ev);
    }
});

// Patch for KanbanController
patch(KanbanController.prototype, {
    async openRecord(ev) {
        console.log("KanbanController openRecord triggered");

        if (this.model.config.resModel === "res.partner") {
            console.log("Condition True");
            console.log("KanbanController: res.partner condition met");
            ev?.stopPropagation?.();

            const record = this.model.root.records.find((rec) => rec.data.res_id === ev.data?.id);
            console.log("KanbanController Record:", record);

            if (record?.data?.view_model && record.data.view_model !== "res.partner") {
                const action = await this.env.services.orm.call(
                    record.data.view_model,
                    "get_formview_action",
                    [[record.data.view_res_id]]
                );
                return this.env.services.action.doAction(action);
            }
        }

        // Default behavior
        return super.openRecord(ev);
    }
});


// /** @odoo-module **/

// import { patch } from "@web/core/utils/patch";
// import { FormController } from "@web/views/form/form_controller";
// import { ListController } from "@web/views/list/list_controller";
// import { KanbanController } from "@web/views/kanban/kanban_controller"; // Import KanbanController

// console.log("This is Partner Controller JS File Loaded in Odoo 17");

// // Store references to the original openRecord methods
// const originalMethods = new Map();

// [FormController, ListController, KanbanController].forEach((Controller) => {
//     if (Controller.prototype.openRecord) {
//         originalMethods.set(Controller, Controller.prototype.openRecord);
//     }
// });

// // Define a common openRecord function
// async function openRecordCommon(ev) {
//     console.log("evvvvv",ev);
    
//     console.log(`This is Global Open Record Function from Salesforce (${this.constructor.name})`);
//     console.log("this.model.config.resModel111",this.model.config.resModel);
    
//     if (this.model.config.resModel === "res.partner") {
//         console.log("Condition True");

//         // Ensure ev is a native event before calling stopPropagation()
//         if (ev && typeof ev.stopPropagation === "function") {
//             ev.stopPropagation();
//         }

//         // Log records to verify structure
//         console.log("Model Records:", this.model.root.records);
//         console.log("Event Data:", ev.data);

//         // Fetch the record correctly in Odoo 17
//         const record = this.model.root.records.find((rec) => rec.data.res_id === ev.data?.id);

//         // if (!record) {
//         //     console.warn("Record not found.");
//         //     return;
//         // }
//         console.log("record",record);
        
//         if (record?.data?.view_model && record.data.view_model !== "res.partner") {
//             const action = await this.env.services.orm.call(
//                 record.data.view_model,
//                 "get_formview_action",
//                 [[record.data.view_res_id]]
//             );
//             this.env.services.action.doAction(action);
//         } else {
//             return originalMethods.get(this.constructor)?.call(this, ev);
//         }
//     } else {
//         console.log("Condition False");
//         return originalMethods.get(this.constructor)?.call(this, ev);
//     }
// }






// // Apply the common function to all controllers
// [FormController, ListController, KanbanController].forEach((Controller) => {
//     patch(Controller.prototype, { openRecord: openRecordCommon });
// });
