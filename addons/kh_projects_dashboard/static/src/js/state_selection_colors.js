/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { StateSelectionField } from "@web/views/fields/state_selection/state_selection_field";

/**
 * Core's StateSelectionField only recognizes two color names: "blocked"
 * (red) and "done" (green) - anything else gets no color at all. Our
 * kh_status field's own values are already literally named "green",
 * "yellow" and "red", so we only need to teach the widget those three
 * names; it does everything else (the clickable dot, the dropdown to
 * change it, hiding the text label in Kanban) on its own already.
 */
patch(StateSelectionField.prototype, {
    setup() {
        super.setup();
        this.colors = { ...this.colors, green: "green", yellow: "yellow", red: "red" };
    },
});
