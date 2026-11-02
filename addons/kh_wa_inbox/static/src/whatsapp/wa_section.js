/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onWillUpdateProps, useEffect, useState } from "@odoo/owl";
import { DASHBOARD_SECTIONS } from "@kh_wa_inbox/dashboard/followup_dashboard";
import { formatDateTime, formatDay, formatMoment, formatTime } from "@kh_wa_inbox/dashboard/dates";

// Odoo's colour-picker palette (index 0 = no colour).
const GROUP_COLORS = [
    "",
    "#F06050",
    "#F4A460",
    "#F7CD1F",
    "#6CC1ED",
    "#814968",
    "#EB7E7F",
    "#2C8397",
    "#475577",
    "#D6145F",
    "#30C381",
    "#9365B8",
];
// The same tests the server uses for the counts, so a tile used as a filter
// shows exactly the items it counted.
const OPEN_FILTERS = {
    needs_manager: (item) => item.needs_manager,
    urgent: (item) => item.urgent,
    overdue: (item) => item.is_overdue,
    open: () => true,
};
const CLOSED_FILTERS = ["closed_week", "avg_close"];
const STATUS_LABELS = { red: "يحتاج انتباه", amber: "متابعة", green: "مستقر" };
const BOX_NUMBERS = [
    { key: "open", label: "مفتوح" },
    { key: "urgent", label: "عاجل" },
    { key: "needs_manager", label: "بانتظار قرارك" },
    { key: "overdue", label: "متأخر" },
];
const REMIND_OPTIONS = [
    { key: "tomorrow", label: "غداً" },
    { key: "3days", label: "بعد 3 أيام" },
    { key: "next_week", label: "الأسبوع القادم" },
];
const KIND_LABELS = { request: "طلب", decision: "قرار مطلوب", deadline: "موعد", alert: "تنبيه" };
const SYNC_ALERT = "البيانات متأخرة";

/**
 * The WhatsApp groups part of لوحة المتابعة: six tiles, one box per group
 * and the follow-up lists. Everything on it comes from one get_dashboard
 * call. Expanded rows, drafts and open boxes live outside the data, so a
 * refresh never closes or moves anything.
 */
export class WhatsAppSection extends Component {
    static template = "kh_wa_inbox.WhatsAppSection";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.ui = useService("ui");
        this.boxNumbers = BOX_NUMBERS;
        this.statusLabels = STATUS_LABELS;
        this.remindOptions = REMIND_OPTIONS;
        this.kindLabels = KIND_LABELS;
        this.state = useState({
            data: null,
            failed: false,
            groupId: null,
            filter: null, // a tile key
            expanded: {},
            contextOpen: {},
            doneDraft: {}, // id -> text while the "تم" box is open
            remindOpen: {},
            assignOpen: {},
            playing: {}, // attachment id -> true once "play" was tapped
            boxOpen: {}, // phone: group boxes unfolded
            closedOpen: false,
            memoDraft: "",
            busy: false,
        });
        this.requestId = 0;
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((next) => {
            if (next.date !== this.props.date || next.search !== this.props.search || next.tick !== this.props.tick) {
                return this.load(next);
            }
        });
        // Only once rendered: changing the frame while this part is still
        // starting would make the frame start it again.
        useEffect(
            (sync) => sync && this.publishSync(sync),
            () => [this.state.data && this.state.data.last_sync]
        );
    }

    // ---- loading ---------------------------------------------------------

    async load(props = this.props) {
        const requestId = ++this.requestId;
        const search = (props.search || "").trim();
        try {
            const data = await this.orm.call("kh.wa.item", "get_dashboard", [], {
                date: props.date || null,
                group_id: this.state.groupId,
                search: search.length >= 2 ? search : null,
            });
            if (requestId === this.requestId) {
                this.state.data = data;
                this.state.failed = false;
            }
        } catch {
            // A missed refresh (phone offline...) keeps the last data on screen.
            if (requestId === this.requestId) {
                this.state.failed = true;
            }
        }
    }

    publishSync(sync) {
        if (this.props.setHeaderNote) {
            this.props.setHeaderNote("whatsapp", {
                text: sync.at ? `آخر تحديث للبيانات: ${sync.label}` : sync.label,
                level: sync.level,
                alert: sync.at && sync.level === "late" ? SYNC_ALERT : "",
            });
        }
    }

    // ---- what is shown ---------------------------------------------------

    get searching() {
        return Boolean(this.state.data && this.state.data.search_results);
    }

    get showingClosedWeek() {
        return CLOSED_FILTERS.includes(this.state.filter);
    }

    matches(item) {
        const test = OPEN_FILTERS[this.state.filter];
        return !test || test(item);
    }

    get view() {
        const sections = this.state.data.sections;
        const keep = (items) => items.filter((item) => this.matches(item));
        return {
            needsManager: keep(sections.needs_manager),
            urgent: keep(sections.urgent),
            upcoming: keep(sections.upcoming),
            open: sections.open
                .map((group) => ({ ...group, items: keep(group.items) }))
                .filter((group) => group.items.length),
            daySummary: sections.day_summary,
            closed: sections.closed,
            memos: sections.memos,
        };
    }

    /** "أُغلق هذا الأسبوع" when a closing tile is the filter. */
    get closedWeekItems() {
        const items = [...this.state.data.closed_week];
        if (this.state.filter === "avg_close") {
            const took = (item) => luxon.DateTime.fromSQL(item.done_at) - luxon.DateTime.fromSQL(item.asked_at);
            items.sort((a, b) => took(b) - took(a));
        }
        return items;
    }

    get tiles() {
        const k = this.state.data.kpis;
        const avg = k.avg_close.duration;
        return [
            { key: "needs_manager", value: k.needs_manager.value, label: "بانتظار قرارك",
              note: k.needs_manager.oldest ? `أقدمها ${k.needs_manager.oldest}` : "" },
            { key: "urgent", value: k.urgent.value, label: "عاجل" },
            { key: "overdue", value: k.overdue.value, label: "متأخر",
              note: k.overdue.oldest ? `أقدمها ${k.overdue.oldest}` : "" },
            { key: "open", value: k.open.value, label: "مفتوح" },
            { key: "closed_week", value: k.closed_week.value, label: "أُغلق هذا الأسبوع" },
            { key: "avg_close", value: avg ? avg.value : "—", unit: avg ? avg.unit : "",
              label: "متوسط مدة الإغلاق هذا الأسبوع", empty: !avg },
        ];
    }

    get fullBoxes() {
        return this.state.data.boxes.filter((box) => !box.compact);
    }

    get compactBoxes() {
        return this.state.data.boxes.filter((box) => box.compact);
    }

    get selectedGroup() {
        return this.state.data.groups.find((group) => group.id === this.state.groupId);
    }

    get isToday() {
        return this.state.data.date === this.state.data.today;
    }

    get dayLabel() {
        return this.isToday ? "اليوم" : formatDay(this.state.data.date);
    }

    get closedTitle() {
        return this.isToday ? "أُغلق اليوم" : `أُغلق ${formatDay(this.state.data.date)}`;
    }

    get daySummaryTitle() {
        return this.isToday ? "ملخص اليوم" : `ملخص ${formatDay(this.state.data.date)}`;
    }

    get quickDoneLabel() {
        const minutes = this.state.data.quick_done_minutes;
        return minutes === 60 ? "أُنجز خلال ساعة" : `أُنجز خلال ${minutes} دقيقة`;
    }

    groupColor(index) {
        return GROUP_COLORS[(index || 0) % GROUP_COLORS.length] || "var(--bs-border-color, #ccc)";
    }

    dateTime(value) {
        return formatDateTime(value);
    }

    time(value) {
        return formatTime(value);
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

    // ---- tiles, groups ---------------------------------------------------

    toggleFilter(key) {
        this.state.filter = this.state.filter === key ? null : key;
    }

    selectGroup(groupId) {
        this.state.groupId = groupId;
        return this.load();
    }

    onBoxClick(box) {
        // Phone: a tap unfolds the box; desktop: the whole page follows the group.
        if (this.ui.isSmall) {
            this.state.boxOpen[box.group_id] = !this.state.boxOpen[box.group_id];
        } else if (this.state.groupId !== box.group_id) {
            this.selectGroup(box.group_id);
        }
    }

    onBoxKeydown(box, ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.onBoxClick(box);
        }
    }

    // ---- rows ------------------------------------------------------------

    toggleRow(item) {
        this.state.expanded[item.id] = !this.state.expanded[item.id];
    }

    onRowKeydown(item, ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.toggleRow(item);
        }
    }

    toggleContext(item) {
        this.state.contextOpen[item.id] = !this.state.contextOpen[item.id];
    }

    toggleClosed() {
        this.state.closedOpen = !this.state.closedOpen;
    }

    async run(item, method, kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call("kh.wa.item", method, [[item.id]], kwargs);
        } finally {
            this.state.busy = false;
            await this.load();
        }
    }

    startDone(item) {
        this.state.doneDraft[item.id] = "";
    }

    cancelDone(item) {
        delete this.state.doneDraft[item.id];
    }

    onDoneInput(item, ev) {
        this.state.doneDraft[item.id] = ev.target.value;
    }

    onDoneKeydown(item, ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.confirmDone(item);
        } else if (ev.key === "Escape") {
            this.cancelDone(item);
        }
    }

    async confirmDone(item) {
        const note = (this.state.doneDraft[item.id] || "").trim();
        delete this.state.doneDraft[item.id];
        await this.run(item, "action_done", { note });
    }

    async setWaiting(item) {
        await this.run(item, "action_waiting");
    }

    async reopen(item) {
        await this.run(item, "action_reopen");
    }

    toggleRemind(item) {
        this.state.remindOpen[item.id] = !this.state.remindOpen[item.id];
        this.state.assignOpen[item.id] = false;
    }

    async remind(item, option) {
        this.state.remindOpen[item.id] = false;
        const date = await this.run(item, "action_remind", { when: option.key });
        this.notification.add(`سأذكّرك ${this.day(date)}`, { type: "success" });
    }

    toggleAssign(item) {
        this.state.assignOpen[item.id] = !this.state.assignOpen[item.id];
        this.state.remindOpen[item.id] = false;
    }

    async assign(item, ev) {
        const userId = parseInt(ev.target.value, 10) || false;
        this.state.assignOpen[item.id] = false;
        this.state.busy = true;
        try {
            await this.orm.write("kh.wa.item", [item.id], { assignee_id: userId });
        } finally {
            this.state.busy = false;
            await this.load();
        }
    }

    play(attachment) {
        this.state.playing[attachment.id] = true;
    }

    openForm(item) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "kh.wa.item",
            res_id: item.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openLinked(item) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: item.linked.model,
            res_id: item.linked.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ---- my notes --------------------------------------------------------

    onMemoKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.addMemo();
        }
    }

    async addMemo() {
        const text = this.state.memoDraft.trim();
        if (!text) {
            return;
        }
        this.state.memoDraft = "";
        await this.orm.create("kh.wa.memo", [{ text }]);
        await this.load();
    }

    async finishMemo(memo) {
        await this.orm.write("kh.wa.memo", [memo.id], { done: true });
        await this.load();
    }

    async togglePin(memo) {
        await this.orm.write("kh.wa.memo", [memo.id], { pinned: !memo.pinned });
        await this.load();
    }
}

registry.category(DASHBOARD_SECTIONS).add(
    "whatsapp",
    { component: WhatsAppSection, title: "قروبات الواتساب" },
    { sequence: 10 }
);
