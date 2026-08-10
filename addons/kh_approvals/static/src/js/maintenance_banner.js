/** @odoo-module **/

import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { Component, useState } from "@odoo/owl";

// بانر عام بيظهر أول ما يفتح أي يوزر أي تطبيق بـ Odoo، مش مرتبط بموديل أو
// تطبيق معيّن - مسجّل بـ main_components (نفس المكان يلي Odoo نفسه بيستخدمه
// لعناصر عامة زي إشعارات النظام)، فبيبقى ظاهر بغض النظر وين المستخدم رايح.
// الرسالة نفسها جايّة من session_info (ir_http.py) - Python بيقرر تفعيلها.
class KhMaintenanceBanner extends Component {
    static template = "kh_approvals.MaintenanceBanner";
    static props = {};

    setup() {
        this.state = useState({ dismissed: false });
    }

    get message() {
        return session.kh_maintenance_banner;
    }

    dismiss() {
        this.state.dismissed = true;
    }
}

registry.category("main_components").add("KhMaintenanceBanner", {
    Component: KhMaintenanceBanner,
});
