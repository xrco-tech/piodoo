/** @odoo-module */
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

let toggledGroupCustom = false;

patch(ListRenderer.prototype, {
    toggleGroup(group) {
        toggledGroupCustom = group;
        super.toggleGroup(group);
    }
});

patch(ListController.prototype, {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    },

    async expandList() {
        let maxDepthReached = false;
        let toggled = false;
        const toggleGroups = (groupList) => {
            groupList.forEach((group) => {
                if (group.isFolded) {
                    group.toggle();
                    toggled = true;
                } else if (group.list.groups?.length > 0) {
                    toggleGroups(group.list.groups);
                    toggled = true;
                } else if (!maxDepthReached && !toggled) {
                    maxDepthReached = true;
                    this.dialog.add(AlertDialog, {
                        title: _t("Alert"),
                        body: _t("Cannot Expand Further!!"),
                    });
                }
            });
        };
        if (toggledGroupCustom?.list?.groups && !toggledGroupCustom.isFolded) {
            toggleGroups(toggledGroupCustom.list.groups);
        } else if (toggledGroupCustom?.isFolded) {
            toggledGroupCustom.toggle();
        }
    },

    async collapseList() {
        const stack = [];
        const collectGroups = (groupList) => {
            groupList.forEach(group => {
                if (!group.isFolded) {
                    stack.push(group);
                } if (group.list?.groups) {
                    collectGroups(group.list.groups);
                }
            });
        };
        collectGroups(this.model.root.groups);
        while (stack.length > 0) {
            const group = stack.pop();
            group.toggle();
        }
        toggledGroupCustom = false;
    },
});
