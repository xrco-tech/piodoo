/* @odoo-module **/

import { VoipSystrayItem } from "@voip/web/voip_systray_item";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(VoipSystrayItem.prototype,{
    async setup() {
        super.setup();
        this.notificationService = useService("notification");
        this.orm = useService("orm");
        this.user = useService("user");
        this.voip_access = false;
        await this.restrictAccessVoip();
    },

    async restrictAccessVoip() {
        await this.orm.call("ir.config_parameter", "get_param", ["sales_force_support.voip_access_group_ids"])
            .then(async (allowedIds) => {
                console.log("allowedIds", allowedIds);
                await this.orm.searchRead("ir.model.data", [["model", "=", "res.groups"],
                    ["res_id", "=", parseInt(allowedIds)]], ["name", "module"])
                    .then(async (group) => {
                        console.log("group", group);
                        if (group && group.length > 0) {
                            let groupName = group[0].module + "." + group[0].name;
                            console.log("groupName", groupName);
                            this.voip_access = await this.user.hasGroup(groupName);
                        } else {
                            console.error("Group not found or empty for ID:", allowedIds);
                        }
                    }).catch((error) => console.error("Error while fetching group:", error));
            }).catch((error) => console.error("Error while fetching parameter:", error));
        await this.handleVoipAccess()
    },

    async handleVoipAccess() {
        const uid = session.uid
        console.log("handleVoipAccess", this.voip_access);
        if(!this.voip_access) {
            $(".o_nav_entry")?.hide();
        }
        this.orm.call("res.users", "update_sip_ignore_incoming",[uid,this.voip_access]);
    },

    async onClick(ev) {
        if(!this.voip_access) {
            ev.preventDefault();
            this.notificationService.add(_t("You do not have access to make a phone call. Please contact ICT for assistance"));
        } else {
            super.onClick(ev);
        }
    },
});
