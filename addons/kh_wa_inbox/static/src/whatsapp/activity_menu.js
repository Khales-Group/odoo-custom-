/** @odoo-module **/

import { ActivityMenu } from "@mail/core/web/activity_menu";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";

/**
 * The manager's WhatsApp activities are his «بانتظار قرارك» To-Dos: clicking
 * them in the activity menu opens the dashboard on that list (where he can
 * decide), not the bare list of every item.
 */
patch(ActivityMenu.prototype, {
    async executeActivityAction(group, domain, views, context, newWindow) {
        if (group.model === "kh.wa.item" && (await user.hasGroup("kh_wa_inbox.group_kh_wa_manager"))) {
            return this.action.doAction("kh_wa_inbox.action_kh_followup_dashboard", {
                newWindow,
                clearBreadcrumbs: true,
                additionalContext: { kh_dashboard_part: "whatsapp", kh_dashboard_view: "needs_manager" },
            });
        }
        return super.executeActivityAction(...arguments);
    },
});
