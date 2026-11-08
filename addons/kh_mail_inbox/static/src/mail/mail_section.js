/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useExternalListener, useState } from "@odoo/owl";
import { DASHBOARD_SECTIONS } from "@kh_wa_inbox/dashboard/followup_dashboard";
import { formatDateTime, formatMoment } from "@kh_wa_inbox/dashboard/dates";
import { FILTERS, MailStore } from "./mail_store";

/** The mail part's entries in the dashboard's sidebar: all boxes, then each one. */
export class MailSidebar extends Component {
    static template = "kh_mail_inbox.MailSidebar";
    static props = ["*"];

    setup() {
        this.store = useState(this.props.store);
    }

    isCurrent(boxId) {
        return this.props.active && (this.store.boxId || null) === (boxId || null);
    }

    open(boxId) {
        this.props.frame.open(this.props.partKey);
        this.store.openBox(boxId);
    }
}

/** The mail part's main area: the list beside the picked message. */
export class MailMain extends Component {
    static template = "kh_mail_inbox.MailMain";
    static props = ["*"];

    setup() {
        this.store = useState(this.props.store);
        this.filters = FILTERS;
        useExternalListener(window, "keydown", (ev) => this.onKeydown(ev));
        useExternalListener(window, "click", (ev) => {
            if (this.store.panel && !ev.target.closest(".o_kh_wa_actionbar")) {
                this.store.panel = null;
            }
        });
    }

    onKeydown(ev) {
        const typing = ev.target.closest && ev.target.closest("input, textarea, select");
        if (ev.key === "Escape") {
            if (this.store.panel) {
                this.store.panel = null;
            } else if (this.store.selectedId) {
                this.store.closeDetail();
            }
        } else if (!typing && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) {
            ev.preventDefault();
            this.store.moveSelection(ev.key === "ArrowDown" ? 1 : -1);
            const row = document.querySelector(".o_kh_mail .o_kh_wa_row.o_kh_wa_selected");
            if (row && row.scrollIntoView) {
                row.scrollIntoView({ block: "nearest" });
            }
        }
    }

    onRowKeydown(row, ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.store.select(row);
        }
    }

    sender(message) {
        return message.from_name || message.from_email || "—";
    }

    moment(value) {
        return formatMoment(value);
    }

    dateTime(value) {
        return formatDateTime(value);
    }

    size(bytes) {
        if (!bytes) {
            return "";
        }
        return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }

    onAssign(ev) {
        this.store.makeTask(parseInt(ev.target.value, 10) || false);
    }
}

registry.category(DASHBOARD_SECTIONS).add(
    "mail",
    {
        title: "الإيميلات",
        makeStore: (services) => new MailStore(services),
        Sidebar: MailSidebar,
        Main: MailMain,
    },
    { sequence: 20 }
);
