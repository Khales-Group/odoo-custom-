/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useExternalListener, useState } from "@odoo/owl";
import { DASHBOARD_SECTIONS } from "@kh_wa_inbox/dashboard/followup_dashboard";
import { formatDateTime, formatDay, formatMoment } from "@kh_wa_inbox/dashboard/dates";
import { GROUP_FILTERS, STATUS_LABELS, VIEWS, WhatsAppStore } from "./wa_store";

const TILES = [
    { key: "needs_manager", label: "بانتظار قرارك" },
    { key: "urgent", label: "عاجل" },
    { key: "overdue", label: "متأخر" },
    { key: "open", label: "مفتوح" },
    { key: "closed_week", label: "أُغلق هذا الأسبوع" },
    { key: "avg_close", label: "متوسط مدة الإغلاق" },
];
const REMIND_OPTIONS = [
    { key: "tomorrow", label: "غداً" },
    { key: "3days", label: "بعد 3 أيام" },
    { key: "next_week", label: "الأسبوع القادم" },
];
const KIND_LABELS = { request: "طلب", decision: "قرار مطلوب", deadline: "موعد", alert: "تنبيه" };
// An approval request's steps (kh.approval.line states).
const STEP_LABELS = { pending: "بانتظار", approved: "وافق", rejected: "رفض", waiting: "لاحقاً", withdrawn: "انسحب" };

/** The WhatsApp part's entries in the dashboard's sidebar. */
export class WhatsAppSidebar extends Component {
    static template = "kh_wa_inbox.WhatsAppSidebar";
    static props = ["*"];

    setup() {
        this.store = useState(this.props.store);
        this.views = VIEWS;
    }

    count(key) {
        return key === "overview" ? null : this.store.totals[key];
    }

    isCurrent(key) {
        return this.props.active && !this.store.groupId && !this.store.searching && this.store.view === key;
    }

    statusLabel(box) {
        return STATUS_LABELS[box.status];
    }

    isCurrentGroup(box) {
        return this.props.active && !this.store.searching && this.store.groupId === box.group_id;
    }

    go(key) {
        this.props.frame.open(this.props.partKey);
        this.store.navigate(key);
    }

    openGroup(box) {
        this.props.frame.open(this.props.partKey);
        this.store.openGroup(box.group_id);
    }
}

/** The WhatsApp part's main area: overview, a list with its item, or my notes. */
export class WhatsAppMain extends Component {
    static template = "kh_wa_inbox.WhatsAppMain";
    static props = ["*"];

    setup() {
        this.store = useState(this.props.store);
        this.tiles = TILES;
        this.groupFilters = GROUP_FILTERS;
        this.remindOptions = REMIND_OPTIONS;
        this.kindLabels = KIND_LABELS;
        this.statusLabels = STATUS_LABELS;
        // Escape closes the open panel, then the item; arrows move in the list.
        useExternalListener(window, "keydown", (ev) => this.onKeydown(ev));
        // A click outside the item's action bar closes its panel.
        useExternalListener(window, "click", (ev) => {
            if (this.store.panel && !ev.target.closest(".o_kh_wa_actionbar")) {
                this.store.panel = null;
            }
        });
    }

    onKeydown(ev) {
        const store = this.store;
        const typing = ev.target.closest && ev.target.closest("input, textarea, select");
        if (ev.key === "Escape") {
            if (store.panel) {
                store.panel = null;
            } else if (store.selectedId || store.groupSummaryOpen) {
                store.closeDetail();
            }
        } else if (!typing && store.mode === "list" && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) {
            ev.preventDefault();
            store.moveSelection(ev.key === "ArrowDown" ? 1 : -1);
            const row = document.querySelector(".o_kh_wa_row.o_kh_wa_selected");
            if (row && row.scrollIntoView) {
                row.scrollIntoView({ block: "nearest" });
            }
        }
    }

    // ---- labels ----------------------------------------------------------

    tileValue(tile) {
        if (tile.key === "avg_close") {
            const avg = this.store.data.kpis.avg_close.duration;
            return avg ? avg.value : "—";
        }
        const value = this.store.data.kpis[tile.key].value;
        return tile.key === "needs_manager" ? value + this.store.approvals.length : value;
    }

    tileUnit(tile) {
        const avg = this.store.data.kpis.avg_close.duration;
        return tile.key === "avg_close" && avg ? avg.unit : "";
    }

    tileNote(tile) {
        const kpi = this.store.data.kpis[tile.key];
        const notes = kpi && kpi.oldest ? [`أقدمها ${kpi.oldest}`] : [];
        const approvals = this.store.approvals.length;
        if (tile.key === "needs_manager" && approvals) {
            notes.unshift(approvals === 1 ? "منها طلب موافقة" : `منها ${approvals} طلبات موافقة`);
        }
        return notes.join(" · ");
    }

    stepLabel(state) {
        return STEP_LABELS[state] || state;
    }

    openTile(tile) {
        if (tile.key === "avg_close") {
            this.store.closedSort = "longest";
            this.store.navigate("closed_week");
        } else {
            this.store.navigate(tile.key);
        }
    }

    color(index) {
        return this.store.groupColor(index);
    }

    dateTime(value) {
        return formatDateTime(value);
    }

    day(value) {
        return formatDay(value);
    }

    moment(value) {
        return formatMoment(value);
    }

    isImage(attachment) {
        return attachment.mimetype.startsWith("image/");
    }

    isAudio(attachment) {
        return attachment.mimetype.startsWith("audio/");
    }

    statLabel(key) {
        return key === "open" ? "مفتوح" : this.store.groupFilterLabel(key);
    }

    // ---- moving around -----------------------------------------------------

    openUpcoming(item) {
        this.store.navigate("open");
        this.store.select(item);
    }

    openClosed(item) {
        this.store.navigate("closed_week");
        this.store.select(item);
    }

    openOldest(box) {
        const item = this.store.findItem(box.oldest.id);
        if (item) {
            this.store.select(item);
        }
    }

    showGroupSummary() {
        this.store.selectedId = null;
        this.store.groupSummaryOpen = true;
    }

    setClosedSort(sort) {
        this.store.closedSort = sort;
    }

    toggleContext() {
        this.store.contextOpen = !this.store.contextOpen;
    }

    // ---- item ------------------------------------------------------------

    onRowKeydown(item, ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.store.select(item);
        }
    }

    onDoneInput(ev) {
        this.store.doneDraft = ev.target.value;
    }

    onDoneKeydown(item, ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.store.confirmDone(item);
        }
    }

    onAssign(item, ev) {
        this.store.assign(item, parseInt(ev.target.value, 10) || false);
    }

    play(attachment) {
        this.store.playing[attachment.id] = true;
    }

    // ---- notes -----------------------------------------------------------

    onMemoInput(ev) {
        this.store.memoDraft = ev.target.value;
    }

    onMemoKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.store.addMemo();
        }
    }
}

registry.category(DASHBOARD_SECTIONS).add(
    "whatsapp",
    {
        title: "قروبات الواتساب",
        makeStore: (services) => new WhatsAppStore(services),
        Sidebar: WhatsAppSidebar,
        Main: WhatsAppMain,
    },
    { sequence: 10 }
);
