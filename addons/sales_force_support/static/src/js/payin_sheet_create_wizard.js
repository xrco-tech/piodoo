/** @odoo-module **/

import { KanbanController } from '@web/views/kanban/kanban_controller';
import { ListController } from '@web/views/list/list_controller';
import { FormController } from '@web/views/form/form_controller';
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";


patch(FormController.prototype, {
    
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    },
    async create(...args) {
        if (this.props.resModel === 'payin.distributor') {
            const action = createAction('bb.payin.distributor.wizard', 'Pay-In Sheet Distributor Summary');
            this.actionService.doAction(action);
        } else if (this.props.resModel === 'bb.payin.sheet') {
            const action = createAction('bb.payin.sheet.wizard', 'Create Pay-In Sheets Pack');
            this.actionService.doAction(action);
        } else {
            super.create(...args);
        }
    }
});

patch(ListController.prototype, {
    
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    },
    async createRecord(...args) {
        if (this.props.resModel === 'payin.distributor') {
            const action = createAction('bb.payin.distributor.wizard', 'Pay-In Sheet Distributor Summary');
            this.actionService.doAction(action);
        } else if (this.props.resModel === 'bb.payin.sheet') {
            const action = createAction('bb.payin.sheet.wizard', 'Create Pay-In Sheets Pack');
            this.actionService.doAction(action);
        } else {
            super.createRecord(...args);
        }
    }
});

patch(KanbanController.prototype, {
    
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    },
    async createRecord(...args) {
        if (this.props.resModel === 'payin.distributor') {
            const action = createAction('bb.payin.distributor.wizard', 'Pay-In Sheet Distributor Summary');
            this.actionService.doAction(action);
        } else if (this.props.resModel === 'bb.payin.sheet') {
            const action = createAction('bb.payin.sheet.wizard', 'Create Pay-In Sheets Pack');
            this.actionService.doAction(action);
        } else {
            super.createRecord(...args);
        }
    }
});

function createAction(wizardModel, actionName) {
    return {
        name: _t(actionName),
        type: 'ir.actions.act_window',
        res_model: wizardModel,
        views: [[false, 'form']],
        target: 'new',
        context: {},
    };
}