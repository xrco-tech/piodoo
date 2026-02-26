/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
// import { KanbanController } from "@web/views/kanban/kanban_controller";

console.log("This is promotions_controller.js loaded...");

// Patch for FormController
patch(FormController.prototype, {
    async openRecord(record) {
        console.log("FormController openRecord triggered");

        const orm = this.env.services.orm;
        const actionService = this.env.services.action;

        if (this.model.config.resModel === "bb.payin.history") {
            console.log("FormController: bb.payin.history condition met");

            const employeeId = record.data.member_id?.[0];
            if (!employeeId) {
                return super.openRecord(record);
            }

            try {
                const action = await orm.call("hr.employee", "get_formview_action", [[employeeId]]);
                return actionService.doAction(action);
            } catch (error) {
                console.error("FormController error:", error);
            }
        }

        return super.openRecord(record);
    }
});

// Patch for ListController
patch(ListController.prototype, {
    async openRecord(record) {
        console.log("ListController openRecord triggered");

        const orm = this.env.services.orm;
        const actionService = this.env.services.action;

        if (this.model.config.resModel === "bb.payin.history") {
            console.log("ListController: bb.payin.history condition met");

            const employeeId = record.data.member_id?.[0];
            if (!employeeId) {
                return super.openRecord(record);
            }

            try {
                const action = await orm.call("hr.employee", "get_formview_action", [[employeeId]]);
                return actionService.doAction(action);
            } catch (error) {
                console.error("ListController error:", error);
            }
        }

        return super.openRecord(record);
    }
});