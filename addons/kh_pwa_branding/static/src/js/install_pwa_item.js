/** @odoo-module **/
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * Core's own installPWAItem (web/static/src/webclient/user_menu/user_menu_items.js)
 * only offers a per-app scoped install (its own icon/shortcut) for
 * "barcode", "field-service" and "shop-floor" - every other app, including
 * ours, just gets the generic whole-Odoo install prompt. The core comment
 * itself says the feature "could work with all apps" - this override lifts
 * that restriction for any app that has a web_icon configured on its root
 * menu (which is also what drives the Apps-switcher tile icon).
 */
function khInstallPWAItem(env) {
    let description = _t("Install App");
    let callback = () => env.services.pwa.show();
    let show = () => env.services.pwa.isAvailable;
    const currentApp = env.services.menu.getCurrentApp();
    if (currentApp && currentApp.webIcon) {
        description = _t("Install %s", currentApp.name);
        callback = () => {
            window.open(
                `/scoped_app?app_id=${currentApp.webIcon.split(",")[0]}&path=${encodeURIComponent(
                    "scoped_app/" + currentApp.actionPath
                )}`
            );
        };
        show = () => !env.services.pwa.isScopedApp;
    }
    return {
        type: "item",
        id: "install_pwa",
        description,
        callback,
        show,
        sequence: 65,
    };
}

registry.category("user_menuitems").add("install_pwa", khInstallPWAItem, { force: true });
