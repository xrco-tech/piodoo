/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        this.__waffleMenuSvc = useService("menu");
        this.__waffleHandler = null;

        onMounted(() => {
            const appsMenu = document.querySelector(".o_main_navbar .o_navbar_apps_menu");
            if (!appsMenu) return;
            this.__waffleHandler = (ev) => {
                ev.preventDefault();
                ev.stopImmediatePropagation();
                const apps = this.__waffleMenuSvc.getApps();
                const homeApp =
                    apps.find((a) => a.xmlid === "home-theme.menu_home_screen") ||
                    apps.find((a) => a.name === "Home");
                if (homeApp) {
                    this.onNavBarDropdownItemSelection(homeApp);
                }
            };
            appsMenu.addEventListener("click", this.__waffleHandler, true);
        });

        onWillUnmount(() => {
            const appsMenu = document.querySelector(".o_main_navbar .o_navbar_apps_menu");
            if (appsMenu && this.__waffleHandler) {
                appsMenu.removeEventListener("click", this.__waffleHandler, true);
            }
        });
    },
});
