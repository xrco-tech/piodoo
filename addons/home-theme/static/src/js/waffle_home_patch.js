/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

patch(NavBar.prototype, {
    goToHome() {
        const apps = this.menuService.getApps();
        const homeApp =
            apps.find((a) => a.xmlid === "home-theme.menu_home_screen") ||
            apps.find((a) => a.name === "Home");
        if (homeApp) {
            this.onNavBarDropdownItemSelection(homeApp);
        }
    },
});
