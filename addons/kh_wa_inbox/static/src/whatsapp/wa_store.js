/** @odoo-module **/

import { markRaw } from "@odoo/owl";
import { user } from "@web/core/user";
import { formatDay, formatMoment } from "@kh_wa_inbox/dashboard/dates";

// Odoo's colour-picker palette (index 0 = no colour).
export const GROUP_COLORS = [
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

// The lists of the sidebar. The tests are the ones the server counts with,
// so a count is always its list's length.
export const VIEWS = [
    { key: "overview", label: "نظرة عامة" },
    { key: "needs_manager", label: "بانتظار قرارك", empty: "لا شيء بانتظار قرارك", test: (i) => i.needs_manager },
    { key: "urgent", label: "عاجل", empty: "لا شيء عاجل", test: (i) => i.urgent },
    { key: "overdue", label: "متأخر", empty: "لا شيء متأخر", test: (i) => i.is_overdue },
    { key: "open", label: "مفتوح", empty: "لا طلبات مفتوحة", test: () => true },
    { key: "closed_week", label: "أُغلق هذا الأسبوع", empty: "لم يُغلق شيء هذا الأسبوع" },
    { key: "notes", label: "ملاحظاتي" },
];
const VIEW = Object.fromEntries(VIEWS.map((v) => [v.key, v]));
// Inside a group, the list can be narrowed with these.
export const GROUP_FILTERS = ["open", "needs_manager", "urgent", "overdue"];
export const STATUS_LABELS = { red: "يحتاج انتباه", amber: "متابعة", green: "مستقر" };
// project.task states, as the item pane names them.
const TASK_STATES = {
    "01_in_progress": "قيد العمل",
    "02_changes_requested": "مطلوب تعديل",
    "03_approved": "موافَق عليها",
    "04_waiting_normal": "بانتظار مهمة أخرى",
    "1_done": "تمت",
    "1_canceled": "ملغاة",
};
const SYNC_ALERT = "البيانات متأخرة";

const byAsked = (a, b) => (a.asked_at || "").localeCompare(b.asked_at || "") || a.id - b.id;
const byDone = (a, b) => (b.done_at || "").localeCompare(a.done_at || "") || b.id - a.id;
const tookMs = (item) => luxon.DateTime.fromSQL(item.done_at) - luxon.DateTime.fromSQL(item.asked_at);

/**
 * Everything the WhatsApp part knows and does, shared by its sidebar and
 * its main area (both observe it with useState). The page is one
 * get_dashboard call; where the user is (view, group, selected item, open
 * panel) lives here too, so a refresh never moves or closes anything.
 */
export class WhatsAppStore {
    constructor(services) {
        this.services = markRaw(services); // orm, action, notification
        this.data = null;
        this.failed = false;
        this.view = "overview";
        this.groupId = null;
        this.groupFilter = "open";
        this.closedSort = "recent"; // or "longest"
        this.selectedId = null;
        this.panel = null; // "done" | "remind" | "assign"
        this.doneDraft = "";
        this.contextOpen = false;
        this.groupSummaryOpen = false; // narrow screens: the group's summary sheet
        this.playing = {};
        this.memoDraft = "";
        this.busy = false;
        this.query = { date: null, search: "" };
        this.requests = markRaw({ last: 0 });
    }

    // ---- loading ---------------------------------------------------------

    async load(query) {
        if (query) {
            this.query = { date: query.date || null, search: query.search || "" };
        }
        const request = ++this.requests.last;
        const search = this.query.search.trim();
        try {
            const data = await this.services.orm.call("kh.wa.item", "get_dashboard", [], {
                date: this.query.date,
                group_id: this.groupId,
                search: search.length >= 2 ? search : null,
            });
            if (request === this.requests.last) {
                this.data = data;
                this.failed = false;
                if (this.selectedId && !this.findItem(this.selectedId)) {
                    this.selectedId = null;
                    this.panel = null;
                }
            }
        } catch {
            // A missed refresh (phone offline...) keeps the last data on screen.
            if (request === this.requests.last) {
                this.failed = true;
            }
        }
    }

    /** The line this part shows at the bottom of the sidebar. */
    get headerNote() {
        const sync = this.data && this.data.last_sync;
        if (!sync) {
            return null;
        }
        return {
            text: sync.at ? `آخر تحديث للبيانات: ${sync.label}` : sync.label,
            level: sync.level,
            alert: sync.at && sync.level === "late" ? SYNC_ALERT : "",
        };
    }

    // ---- where the user is ---------------------------------------------------

    get searching() {
        return Boolean(this.data && this.data.search_results);
    }

    /** "overview", "notes" or "list". */
    get mode() {
        if (this.searching) {
            return "list";
        }
        if (this.groupId) {
            return "list";
        }
        return this.view === "overview" || this.view === "notes" ? this.view : "list";
    }

    /** The list's own key: a view, or the filter inside a group. */
    get listKey() {
        if (this.searching) {
            return "search";
        }
        return this.groupId ? this.groupFilter : this.view;
    }

    get heading() {
        const data = this.data;
        if (!data) {
            return { title: "قروبات الواتساب" };
        }
        if (this.searching) {
            return { title: "نتائج البحث", count: data.search_results.length, sub: `عن «${this.query.search.trim()}»` };
        }
        if (this.groupId) {
            const box = this.selectedBox;
            if (!box) {
                return { title: "", count: this.listItems.length };
            }
            const last = box.last_message_at ? `آخر رسالة ${formatMoment(box.last_message_at)}` : "لا رسائل بعد";
            return { title: box.name, count: this.listItems.length, sub: `${STATUS_LABELS[box.status]} · ${last}` };
        }
        if (this.view === "overview") {
            return { title: "نظرة عامة", sub: "قروبات الواتساب" };
        }
        if (this.view === "notes") {
            return { title: "ملاحظاتي", count: data.sections.memos.length };
        }
        return { title: VIEW[this.view].label, count: this.listItems.length };
    }

    navigate(view) {
        const leavingGroup = Boolean(this.groupId);
        this.view = view;
        this.groupId = null;
        this.resetSelection();
        if (leavingGroup) {
            return this.load();
        }
    }

    openGroup(groupId) {
        if (this.groupId === groupId && !this.searching) {
            return;
        }
        this.groupId = groupId;
        this.groupFilter = "open";
        this.resetSelection();
        return this.load();
    }

    setGroupFilter(key) {
        this.groupFilter = key;
        this.resetSelection();
    }

    resetSelection() {
        this.selectedId = null;
        this.panel = null;
        this.contextOpen = false;
        this.groupSummaryOpen = false;
    }

    select(item) {
        if (this.selectedId !== item.id) {
            this.selectedId = item.id;
            this.panel = null;
            this.doneDraft = "";
            this.contextOpen = false;
        }
    }

    closeDetail() {
        this.selectedId = null;
        this.panel = null;
        this.groupSummaryOpen = false;
    }

    /** Arrow keys in the list. */
    moveSelection(step) {
        const items = this.flatList;
        if (!items.length) {
            return;
        }
        const index = items.findIndex((item) => item.id === this.selectedId);
        const next = index < 0 ? (step > 0 ? 0 : items.length - 1) : Math.min(Math.max(index + step, 0), items.length - 1);
        this.select(items[next]);
    }

    // ---- what is shown -------------------------------------------------------

    /** Totals of every group (the sidebar's counts don't follow a picked group). */
    get totals() {
        const boxes = (this.data && this.data.boxes) || [];
        const sum = (key) => boxes.reduce((total, box) => total + box.counts[key], 0);
        return {
            needs_manager: sum("needs_manager"),
            urgent: sum("urgent"),
            overdue: sum("overdue"),
            open: sum("open"),
            closed_week: boxes.reduce((total, box) => total + box.week.closed, 0),
            notes: this.data ? this.data.sections.memos.length : 0,
        };
    }

    /** The sidebar's groups, in their fixed order (not by status). */
    get navGroups() {
        if (!this.data) {
            return [];
        }
        const boxes = Object.fromEntries(this.data.boxes.map((box) => [box.group_id, box]));
        return this.data.groups.filter((group) => boxes[group.id]).map((group) => boxes[group.id]);
    }

    get openItems() {
        const s = this.data.sections;
        return [...s.needs_manager, ...s.urgent, ...s.upcoming, ...s.open.flatMap((g) => g.items)].sort(byAsked);
    }

    get listItems() {
        const key = this.listKey;
        if (key === "search") {
            return this.data.search_results;
        }
        if (key === "closed_week") {
            const items = [...this.data.closed_week];
            return items.sort(this.closedSort === "longest" ? (a, b) => tookMs(b) - tookMs(a) : byDone);
        }
        if (!VIEW[key] || !VIEW[key].test) {
            return [];
        }
        const items = this.openItems.filter(VIEW[key].test);
        if (key === "needs_manager") {
            items.sort((a, b) => b.urgent - a.urgent || byAsked(a, b));
        } else if (key === "overdue") {
            items.sort((a, b) => a.due_date.localeCompare(b.due_date) || byAsked(a, b));
        }
        return items;
    }

    /** The global "مفتوح" list, by group. */
    get listGroups() {
        if (this.listKey !== "open" || this.groupId) {
            return null;
        }
        const items = this.listItems;
        return this.navGroups
            .map((box) => ({ ...box, items: items.filter((item) => item.group_id === box.group_id) }))
            .filter((group) => group.items.length);
    }

    /** The list in screen order (for the arrow keys). */
    get flatList() {
        const groups = this.listGroups;
        return groups ? groups.flatMap((group) => group.items) : this.listItems;
    }

    get emptyText() {
        const key = this.listKey;
        return key === "search" ? "لا نتائج." : (VIEW[key] && VIEW[key].empty) || "";
    }

    groupFilterLabel(key) {
        return key === "open" ? "الكل" : VIEW[key].label;
    }

    groupFilterCount(key) {
        return this.data.kpis[key].value;
    }

    findItem(id) {
        const d = this.data;
        return (
            this.openItems.find((i) => i.id === id) ||
            d.closed_week.find((i) => i.id === id) ||
            d.sections.closed.find((i) => i.id === id) ||
            (d.search_results || []).find((i) => i.id === id) ||
            null
        );
    }

    get selectedItem() {
        return this.data && this.selectedId ? this.findItem(this.selectedId) : null;
    }

    get selectedBox() {
        return this.data ? this.data.boxes.find((box) => box.selected) : null;
    }

    get upcoming() {
        const limit = luxon.DateTime.fromISO(this.data.today).plus({ days: 7 }).toISODate();
        return this.openItems
            .filter((item) => item.kind === "deadline" && item.due_date && item.due_date <= limit)
            .sort((a, b) => a.due_date.localeCompare(b.due_date));
    }

    get isToday() {
        return this.data.date === this.data.today;
    }

    get dayLabel() {
        return this.isToday ? "اليوم" : formatDay(this.data.date);
    }

    get quickDoneLabel() {
        const minutes = this.data.quick_done_minutes;
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
        return this.shortName(item.assignee.name);
    }

    shortName(name) {
        const parts = (name || "").trim().split(/\s+/);
        return parts.length > 2 ? `${parts[0]} ${parts[parts.length - 1]}` : name;
    }

    isClosed(item) {
        return item.state === "done" || item.state === "cancel";
    }

    // ---- actions on an item -------------------------------------------------------

    togglePanel(kind) {
        this.panel = this.panel === kind ? null : kind;
        this.doneDraft = "";
    }

    async run(item, method, kwargs = {}, { close = false } = {}) {
        this.busy = true;
        this.panel = null;
        if (close) {
            this.selectedId = null;
        }
        try {
            return await this.services.orm.call("kh.wa.item", method, [[item.id]], kwargs);
        } finally {
            this.busy = false;
            await this.load();
        }
    }

    async confirmDone(item) {
        const note = this.doneDraft.trim();
        this.doneDraft = "";
        await this.run(item, "action_done", { note }, { close: true });
    }

    setWaiting(item) {
        return this.run(item, "action_waiting");
    }

    sendTask(item) {
        return this.run(item, "action_send_task");
    }

    /** "قيد العمل عند نزار · حتى ٩ نوفمبر" */
    taskLine(item) {
        const task = item.task;
        const parts = [`${TASK_STATES[task.state] || task.state} عند ${this.shortName(task.user) || "—"}`];
        if (task.deadline && !task.closed) {
            parts.push(`حتى ${formatDay(task.deadline)}`);
        }
        return parts.join(" · ");
    }

    reopen(item) {
        return this.run(item, "action_reopen", {}, { close: true });
    }

    async remind(item, when) {
        const date = await this.run(item, "action_remind", { when });
        this.services.notification.add(`سأذكّرك ${formatDay(date)}`, { type: "success" });
    }

    async assign(item, userId) {
        this.panel = null;
        this.busy = true;
        try {
            await this.services.orm.write("kh.wa.item", [item.id], { assignee_id: userId || false });
        } finally {
            this.busy = false;
            await this.load();
        }
    }

    openForm(item) {
        this.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "kh.wa.item",
            res_id: item.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openTask(item) {
        this.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: item.task.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async linkRecord(item) {
        const action = await this.services.orm.call("kh.wa.item", "action_link_record", [[item.id]]);
        await this.services.action.doAction(action, { onClose: () => this.load() });
    }

    openLinked(item) {
        this.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: item.linked.model,
            res_id: item.linked.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ---- my notes -------------------------------------------------------------------

    async addMemo() {
        const text = this.memoDraft.trim();
        if (!text) {
            return;
        }
        this.memoDraft = "";
        await this.services.orm.create("kh.wa.memo", [{ text }]);
        await this.load();
    }

    async finishMemo(memo) {
        await this.services.orm.write("kh.wa.memo", [memo.id], { done: true });
        await this.load();
    }

    async togglePin(memo) {
        await this.services.orm.write("kh.wa.memo", [memo.id], { pinned: !memo.pinned });
        await this.load();
    }
}
