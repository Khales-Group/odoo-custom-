/** @odoo-module **/

import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onWillUpdateProps, useEffect, useExternalListener, useState } from "@odoo/owl";
import { DASHBOARD_SECTIONS } from "@kh_wa_inbox/dashboard/followup_dashboard";
import { formatDateTime, formatDay, formatMoment } from "@kh_wa_inbox/dashboard/dates";

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
// The six tiles are also the tabs of the main list. The tests are the ones
// the server counts with, so a tile's number is its list's length.
const TILES = [
    { key: "needs_manager", label: "بانتظار قرارك", empty: "لا شيء بانتظار قرارك", test: (i) => i.needs_manager },
    { key: "urgent", label: "عاجل", empty: "لا شيء عاجل", test: (i) => i.urgent },
    { key: "overdue", label: "متأخر", empty: "لا شيء متأخر", test: (i) => i.is_overdue },
    { key: "open", label: "مفتوح", empty: "لا طلبات مفتوحة", test: () => true },
    { key: "closed_week", label: "أُغلق هذا الأسبوع", empty: "لم يُغلق شيء هذا الأسبوع" },
    { key: "avg_close", label: "متوسط مدة الإغلاق", empty: "لم يُغلق شيء هذا الأسبوع" },
];
const CARD_NUMBERS = [
    { key: "open", label: "مفتوح" },
    { key: "urgent", label: "عاجل" },
    { key: "needs_manager", label: "قرارك", title: "بانتظار قرارك" },
    { key: "overdue", label: "متأخر" },
];
const STATUS_LABELS = { red: "يحتاج انتباه", amber: "متابعة", green: "مستقر" };
const REMIND_OPTIONS = [
    { key: "tomorrow", label: "غداً" },
    { key: "3days", label: "بعد 3 أيام" },
    { key: "next_week", label: "الأسبوع القادم" },
];
const KIND_LABELS = { request: "طلب", decision: "قرار مطلوب", deadline: "موعد", alert: "تنبيه" };
const SYNC_ALERT = "البيانات متأخرة";

const byAsked = (a, b) => (a.asked_at || "").localeCompare(b.asked_at || "") || a.id - b.id;
const tookMs = (item) => luxon.DateTime.fromSQL(item.done_at) - luxon.DateTime.fromSQL(item.asked_at);

/**
 * The WhatsApp groups part of لوحة المتابعة: six tiles (which pick the list
 * shown), one compact card per group, the list, and a side column (picked
 * group, coming dates, the day's summary, closed today, my notes).
 * Everything comes from one get_dashboard call. The open row, its panel and
 * drafts live outside the data, so a refresh never closes or moves anything.
 */
export class WhatsAppSection extends Component {
    static template = "kh_wa_inbox.WhatsAppSection";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.tiles = TILES;
        this.cardNumbers = CARD_NUMBERS;
        this.statusLabels = STATUS_LABELS;
        this.remindOptions = REMIND_OPTIONS;
        this.kindLabels = KIND_LABELS;
        this.state = useState({
            data: null,
            failed: false,
            groupId: null,
            tab: null, // a tile key; null = the first tile with something in it
            openId: null, // the one expanded row
            panel: null, // "done" | "remind" | "assign", for the open row
            doneDraft: "",
            contextOpen: false,
            playing: {}, // attachment id -> true once "play" was tapped
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
        // Escape closes the panel, then the row; a click elsewhere closes the panel.
        useExternalListener(window, "keydown", (ev) => {
            if (ev.key !== "Escape") {
                return;
            }
            if (this.state.panel) {
                this.state.panel = null;
            } else if (this.state.openId) {
                this.state.openId = null;
            }
        });
        useExternalListener(window, "click", (ev) => {
            if (this.state.panel && !ev.target.closest(".o_kh_wa_row.o_kh_wa_open")) {
                this.state.panel = null;
            }
        });
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

    // ---- tiles and the list ----------------------------------------------

    get kpis() {
        return this.state.data.kpis;
    }

    tileValue(tile) {
        if (tile.key === "avg_close") {
            const avg = this.kpis.avg_close.duration;
            return avg ? avg.value : "—";
        }
        return this.kpis[tile.key].value;
    }

    tileUnit(tile) {
        const avg = this.kpis.avg_close.duration;
        return tile.key === "avg_close" && avg ? avg.unit : "";
    }

    tileNote(tile) {
        return this.kpis[tile.key] && this.kpis[tile.key].oldest ? `أقدمها ${this.kpis[tile.key].oldest}` : "";
    }

    get activeTab() {
        if (this.state.tab) {
            return this.state.tab;
        }
        const first = TILES.slice(0, 3).find((tile) => this.kpis[tile.key].value);
        return first ? first.key : "open";
    }

    get activeTile() {
        return TILES.find((tile) => tile.key === this.activeTab);
    }

    get searching() {
        return Boolean(this.state.data.search_results);
    }

    /** Every open item of the picked group (or of all groups). */
    get openItems() {
        const s = this.state.data.sections;
        return [...s.needs_manager, ...s.urgent, ...s.upcoming, ...s.open.flatMap((g) => g.items)].sort(byAsked);
    }

    get listItems() {
        if (this.searching) {
            return this.state.data.search_results;
        }
        const tab = this.activeTab;
        if (tab === "closed_week") {
            return this.state.data.closed_week;
        }
        if (tab === "avg_close") {
            return [...this.state.data.closed_week].sort((a, b) => tookMs(b) - tookMs(a));
        }
        const items = this.openItems.filter(this.activeTile.test);
        if (tab === "needs_manager") {
            items.sort((a, b) => b.urgent - a.urgent || byAsked(a, b));
        } else if (tab === "overdue") {
            items.sort((a, b) => a.due_date.localeCompare(b.due_date) || byAsked(a, b));
        }
        return items;
    }

    /** The "مفتوح" tab, by group in the cards' order. */
    get listGroups() {
        const items = this.listItems;
        return this.state.data.boxes
            .map((box) => ({ ...box, items: items.filter((item) => item.group_id === box.group_id) }))
            .filter((group) => group.items.length);
    }

    get groupedList() {
        return !this.searching && this.activeTab === "open" && !this.state.groupId;
    }

    get listTitle() {
        return this.searching ? "نتائج البحث" : this.activeTile.label;
    }

    get listNote() {
        return !this.searching && this.activeTab === "avg_close" ? "الأطول مدة أولاً" : "";
    }

    get emptyText() {
        return this.searching ? "لا نتائج." : this.activeTile.empty;
    }

    selectTab(key) {
        this.state.tab = key;
        this.state.openId = null;
        this.state.panel = null;
    }

    // ---- groups ----------------------------------------------------------

    get cards() {
        return this.state.data.boxes.filter((box) => !box.compact);
    }

    get quietCards() {
        return this.state.data.boxes.filter((box) => box.compact);
    }

    get selectedBox() {
        return this.state.data.boxes.find((box) => box.selected);
    }

    selectGroup(groupId) {
        this.state.groupId = this.state.groupId === groupId ? null : groupId;
        this.state.openId = null;
        this.state.panel = null;
        return this.load();
    }

    onCardKeydown(box, ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.selectGroup(box.group_id);
        }
    }

    /** From the side column: show an open item in the main list. */
    focusItem(id) {
        this.state.tab = "open";
        this.state.openId = id;
        this.state.panel = null;
    }

    focusClosed(id) {
        this.state.tab = "closed_week";
        this.state.openId = id;
        this.state.panel = null;
    }

    get upcoming() {
        const limit = luxon.DateTime.fromISO(this.state.data.today).plus({ days: 7 }).toISODate();
        return this.openItems
            .filter((item) => item.kind === "deadline" && item.due_date && item.due_date <= limit)
            .sort((a, b) => a.due_date.localeCompare(b.due_date));
    }

    // ---- labels ----------------------------------------------------------

    get isToday() {
        return this.state.data.date === this.state.data.today;
    }

    get dayLabel() {
        return this.isToday ? "اليوم" : formatDay(this.state.data.date);
    }

    get quickDoneLabel() {
        const minutes = this.state.data.quick_done_minutes;
        return minutes === 60 ? "أُنجز خلال ساعة" : `أُنجز خلال ${minutes} دقيقة`;
    }

    groupColor(index) {
        return GROUP_COLORS[(index || 0) % GROUP_COLORS.length] || "var(--border-color, #ccc)";
    }

    /** "Majed Salem Saif Salem Alkindi" -> "Majed Alkindi"; nothing when it's me. */
    who(item) {
        if (!item.assignee) {
            return this.isClosed(item) ? "" : "بلا مسؤول";
        }
        if (item.assignee.id === user.userId) {
            return "";
        }
        const parts = item.assignee.name.trim().split(/\s+/);
        return parts.length > 2 ? `${parts[0]} ${parts[parts.length - 1]}` : item.assignee.name;
    }

    isClosed(item) {
        return item.state === "done" || item.state === "cancel";
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

    // ---- rows ------------------------------------------------------------

    toggleRow(item) {
        this.state.openId = this.state.openId === item.id ? null : item.id;
        this.state.panel = null;
        this.state.contextOpen = false;
    }

    onRowKeydown(item, ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.toggleRow(item);
        }
    }

    togglePanel(kind) {
        this.state.panel = this.state.panel === kind ? null : kind;
        this.state.doneDraft = "";
    }

    toggleContext() {
        this.state.contextOpen = !this.state.contextOpen;
    }

    toggleClosed() {
        this.state.closedOpen = !this.state.closedOpen;
    }

    async run(item, method, kwargs = {}, { close = false } = {}) {
        this.state.busy = true;
        this.state.panel = null;
        if (close) {
            this.state.openId = null;
        }
        try {
            return await this.orm.call("kh.wa.item", method, [[item.id]], kwargs);
        } finally {
            this.state.busy = false;
            await this.load();
        }
    }

    onDoneInput(ev) {
        this.state.doneDraft = ev.target.value;
    }

    onDoneKeydown(item, ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.confirmDone(item);
        }
    }

    async confirmDone(item) {
        const note = this.state.doneDraft.trim();
        this.state.doneDraft = "";
        await this.run(item, "action_done", { note }, { close: true });
    }

    async setWaiting(item) {
        await this.run(item, "action_waiting");
    }

    async reopen(item) {
        await this.run(item, "action_reopen", {}, { close: true });
    }

    async remind(item, option) {
        const date = await this.run(item, "action_remind", { when: option.key });
        this.notification.add(`سأذكّرك ${this.day(date)}`, { type: "success" });
    }

    async assign(item, ev) {
        const userId = parseInt(ev.target.value, 10) || false;
        this.state.panel = null;
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
