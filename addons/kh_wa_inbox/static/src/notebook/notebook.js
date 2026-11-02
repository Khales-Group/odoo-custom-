/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";

// The notebook always reads in Arabic, right to left, in Dubai time, with
// Latin digits - whatever the user's Odoo language is.
const ZONE = "Asia/Dubai";
const REFRESH_MS = 60 * 1000;
const SEARCH_DELAY_MS = 350;
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

const COUNTERS = [
    { key: "needs_manager", label: "بانتظار قرارك" },
    { key: "urgent", label: "عاجل" },
    { key: "overdue", label: "متأخر" },
    { key: "open", label: "مفتوح" },
];
// The same tests the server uses for the counters, so a counter used as a
// filter shows exactly the items it counted.
const COUNTER_TESTS = {
    needs_manager: (item) => item.needs_manager,
    urgent: (item) => item.urgent,
    overdue: (item) => item.is_overdue,
    open: () => true,
};
const REMIND_OPTIONS = [
    { key: "tomorrow", label: "غداً" },
    { key: "3days", label: "بعد 3 أيام" },
    { key: "next_week", label: "الأسبوع القادم" },
];
const KIND_LABELS = { request: "طلب", decision: "قرار مطلوب", deadline: "موعد", alert: "تنبيه" };
const STATE_LABELS = { open: "مفتوح", waiting: "بانتظار رد", done: "تم", cancel: "ملغى" };

function arabic(dt) {
    return dt.reconfigure({ locale: "ar", numberingSystem: "latn" });
}

function fromUtc(value) {
    return value ? arabic(luxon.DateTime.fromSQL(value, { zone: "utc" }).setZone(ZONE)) : null;
}

function fromDay(value) {
    return value ? arabic(luxon.DateTime.fromISO(value, { zone: ZONE })) : null;
}

export class GroupsNotebook extends Component {
    static template = "kh_wa_inbox.Notebook";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.counters = COUNTERS;
        this.remindOptions = REMIND_OPTIONS;
        this.kindLabels = KIND_LABELS;
        this.stateLabels = STATE_LABELS;
        this.state = useState({
            data: null,
            failed: false,
            date: null, // null = today
            groupId: null,
            filter: null, // one of the counter keys
            search: "",
            // Per item id, kept across refreshes:
            expanded: {},
            contextOpen: {},
            doneDraft: {}, // id -> text while the "تم" box is open
            remindOpen: {},
            assignOpen: {},
            playing: {}, // attachment id -> true once "play" was tapped
            closedOpen: false,
            memoDraft: "",
            busy: false,
        });
        this.requestId = 0;
        this.onVisibilityChange = () => {
            if (!document.hidden) {
                this.load();
            }
        };

        onWillStart(() => this.load());
        onMounted(() => {
            this.timer = setInterval(() => {
                if (!document.hidden) {
                    this.load();
                }
            }, REFRESH_MS);
            document.addEventListener("visibilitychange", this.onVisibilityChange);
        });
        onWillUnmount(() => {
            clearInterval(this.timer);
            clearTimeout(this.searchTimer);
            document.removeEventListener("visibilitychange", this.onVisibilityChange);
        });
    }

    // ---- loading ---------------------------------------------------------

    /**
     * Fetches the whole page in one call. Only the latest request is used,
     * and the expanded rows, drafts and scroll position live outside the
     * data, so a refresh never closes or jumps anything.
     */
    async load() {
        const requestId = ++this.requestId;
        const search = this.state.search.trim();
        try {
            const data = await this.orm.call("kh.wa.item", "get_notebook", [], {
                date: this.state.date,
                group_id: this.state.groupId,
                search: search.length >= 2 ? search : null,
            });
            if (requestId === this.requestId) {
                this.state.data = data;
                this.state.failed = false;
            }
        } catch {
            // A missed refresh (phone offline...) keeps the last page on screen.
            if (requestId === this.requestId) {
                this.state.failed = true;
            }
        }
    }

    // ---- what is shown ---------------------------------------------------

    get searching() {
        return Boolean(this.state.data && this.state.data.search_results);
    }

    matches(item) {
        const test = COUNTER_TESTS[this.state.filter];
        return !test || test(item);
    }

    get view() {
        const sections = this.state.data.sections;
        const keep = (items) => items.filter((item) => this.matches(item));
        return {
            needsManager: keep(sections.needs_manager),
            urgent: keep(sections.urgent),
            open: sections.open
                .map((group) => ({ ...group, items: keep(group.items) }))
                .filter((group) => group.items.length),
            upcoming: keep(sections.upcoming),
            daySummary: sections.day_summary,
            closed: sections.closed,
            memos: sections.memos,
        };
    }

    get isToday() {
        return this.state.data.date === this.state.data.today;
    }

    get pageDate() {
        return fromDay(this.state.data.date).toFormat("cccc d LLLL yyyy");
    }

    get closedTitle() {
        return this.isToday ? "أُغلق اليوم" : `أُغلق ${fromDay(this.state.data.date).toFormat("cccc d LLLL")}`;
    }

    get daySummaryTitle() {
        return this.isToday ? "ملخص اليوم" : `ملخص ${fromDay(this.state.data.date).toFormat("cccc d LLLL")}`;
    }

    get quickDoneLabel() {
        const minutes = this.state.data.quick_done_minutes;
        return minutes === 60 ? "أُنجز خلال ساعة" : `أُنجز خلال ${minutes} دقيقة`;
    }

    groupColor(index) {
        return GROUP_COLORS[(index || 0) % GROUP_COLORS.length] || "var(--bs-border-color, #ccc)";
    }

    dateTime(value) {
        const dt = fromUtc(value);
        return dt ? dt.toFormat("cccc d LLLL، HH:mm") : "";
    }

    time(value) {
        const dt = fromUtc(value);
        return dt ? dt.toFormat("HH:mm") : "";
    }

    day(value) {
        const dt = fromDay(value);
        return dt ? dt.toFormat("cccc d LLLL") : "";
    }

    isImage(attachment) {
        return attachment.mimetype.startsWith("image/");
    }

    isAudio(attachment) {
        return attachment.mimetype.startsWith("audio/");
    }

    // ---- header ----------------------------------------------------------

    toggleFilter(key) {
        this.state.filter = this.state.filter === key ? null : key;
    }

    selectGroup(groupId) {
        this.state.groupId = groupId;
        this.load();
    }

    onDateChange(ev) {
        const value = ev.target.value;
        this.state.date = value && value !== this.state.data.today ? value : null;
        this.load();
    }

    backToToday() {
        this.state.date = null;
        this.load();
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.load(), SEARCH_DELAY_MS);
    }

    clearSearch() {
        this.state.search = "";
        clearTimeout(this.searchTimer);
        this.load();
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

    toggleClosed() {
        this.state.closedOpen = !this.state.closedOpen;
    }

    toggleContext(item) {
        this.state.contextOpen[item.id] = !this.state.contextOpen[item.id];
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

registry.category("actions").add("kh_wa_inbox.notebook", GroupsNotebook);
