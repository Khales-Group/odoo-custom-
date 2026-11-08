/** @odoo-module **/

import { markRaw } from "@odoo/owl";
import { formatMoment } from "@kh_wa_inbox/dashboard/dates";
import { GROUP_COLORS } from "@kh_wa_inbox/whatsapp/wa_store";

const PAGE = 50;
export const FILTERS = [
    { key: "all", label: "الكل" },
    { key: "unread", label: "غير مقروء" },
    { key: "needs_reply", label: "تحتاج رد" },
];
const TASK_STATES = {
    "01_in_progress": "قيد العمل",
    "02_changes_requested": "مطلوب تعديل",
    "03_approved": "موافَق عليها",
    "04_waiting_normal": "بانتظار مهمة أخرى",
    "1_done": "تمت",
    "1_canceled": "ملغاة",
};

/**
 * The mail part's state, shared by its sidebar and main area. The list is
 * one page of get_mail_dashboard (newest first, more on request); the
 * picked message comes from get_mail_detail.
 */
export class MailStore {
    constructor(services) {
        this.services = markRaw(services); // orm, action, notification
        this.data = null;
        this.failed = false;
        this.boxId = null; // null = all the mailboxes
        this.filter = "all";
        this.limit = PAGE;
        this.search = "";
        this.selectedId = null;
        this.detail = null;
        this.panel = null; // "task"
        this.busy = false;
        this.requests = markRaw({ last: 0, detail: 0 });
    }

    async load(query) {
        if (query && (query.search || "") !== this.search) {
            this.search = query.search || "";
            this.limit = PAGE;
        }
        const request = ++this.requests.last;
        try {
            const data = await this.services.orm.call("kh.mail.message", "get_mail_dashboard", [], {
                box_id: this.boxId || false,
                filter: this.filter,
                search: this.search.length >= 2 ? this.search : "",
                limit: this.limit,
            });
            if (request === this.requests.last) {
                this.data = data;
                this.failed = false;
            }
        } catch {
            // A missed refresh keeps the last page on screen.
            if (request === this.requests.last) {
                this.failed = true;
            }
        }
    }

    // ---- what the frame shows ------------------------------------------------

    get box() {
        return (this.data && this.boxId && this.data.boxes.find((b) => b.id === this.boxId)) || null;
    }

    get heading() {
        if (!this.data) {
            return { title: "الإيميلات" };
        }
        const count = this.data.filter_counts[this.filter];
        if (this.search.length >= 2) {
            return { title: "نتائج البحث", count, sub: `عن «${this.search}» في ${this.box ? this.box.email : "كل الصناديق"}` };
        }
        const box = this.box;
        return { title: box ? box.email : "كل الصناديق", count, sub: this.importNote(box) };
    }

    /** "يُستورد الأرشيف: 12,300 من 48,451" while a box's history comes in. */
    importNote(box) {
        const boxes = box ? [box] : this.data.boxes;
        const pending = boxes.filter((b) => !b.history_done && b.server_count);
        if (!pending.length) {
            return "";
        }
        const done = pending.reduce((n, b) => n + b.counts.total, 0);
        const all = pending.reduce((n, b) => n + b.server_count, 0);
        return `يُستورد الأرشيف: ${done.toLocaleString("en")} من ${all.toLocaleString("en")}`;
    }

    get headerNote() {
        const sync = this.data && this.data.sync;
        if (!sync) {
            return null;
        }
        if (!sync.at) {
            return { text: "الإيميل: لم تُقرأ الصناديق بعد", level: "warn" };
        }
        const level = sync.minutes >= 120 ? "late" : sync.minutes >= 30 ? "warn" : "ok";
        return {
            text: `الإيميل: آخر قراءة ${formatMoment(sync.at)}`,
            level: sync.errors.length ? "late" : level,
            alert: sync.errors.length ? `تعذّر الاتصال بـ ${sync.errors.join("، ")}` : "",
        };
    }

    boxColor(index) {
        return GROUP_COLORS[(index || 0) % GROUP_COLORS.length] || "var(--border-color, #ccc)";
    }

    get unreadTotal() {
        return this.data ? this.data.boxes.reduce((n, b) => n + b.counts.unread, 0) : 0;
    }

    // ---- moving around ---------------------------------------------------------

    openBox(boxId) {
        this.boxId = boxId || null;
        this.limit = PAGE;
        this.closeDetail();
        return this.load();
    }

    setFilter(key) {
        this.filter = key;
        this.limit = PAGE;
        this.closeDetail();
        return this.load();
    }

    loadMore() {
        this.limit += PAGE;
        return this.load();
    }

    get rows() {
        return this.data ? this.data.messages : [];
    }

    async select(row) {
        this.selectedId = row.id;
        this.panel = null;
        this.detail = null;
        await this.reloadDetail();
    }

    async reloadDetail() {
        if (!this.selectedId) {
            return;
        }
        const request = ++this.requests.detail;
        try {
            const detail = await this.services.orm.call("kh.mail.message", "get_mail_detail", [[this.selectedId]]);
            if (request === this.requests.detail) {
                this.detail = detail;
            }
        } catch {
            if (request === this.requests.detail) {
                this.selectedId = null;
            }
        }
    }

    closeDetail() {
        this.selectedId = null;
        this.detail = null;
        this.panel = null;
    }

    moveSelection(step) {
        const rows = this.rows;
        if (!rows.length) {
            return;
        }
        const index = rows.findIndex((r) => r.id === this.selectedId);
        const next = rows[Math.min(Math.max(index + step, 0), rows.length - 1)];
        if (next && next.id !== this.selectedId) {
            this.select(next);
        }
    }

    // ---- actions ---------------------------------------------------------------

    togglePanel(name) {
        this.panel = this.panel === name ? null : name;
    }

    async run(method, kwargs = {}) {
        this.busy = true;
        this.panel = null;
        try {
            return await this.services.orm.call("kh.mail.message", method, [[this.selectedId]], kwargs);
        } finally {
            this.busy = false;
            await Promise.all([this.load(), this.reloadDetail()]);
        }
    }

    setFollowed(followed) {
        return this.run("action_set_followed", { followed });
    }

    async makeTask(userId) {
        if (!userId) {
            return;
        }
        await this.run("action_make_task", { user_id: userId });
        this.services.notification.add("أُرسلت المهمة", { type: "success" });
    }

    taskLine(task) {
        return `${TASK_STATES[task.state] || task.state} عند ${task.user || "—"}`;
    }

    openTask(task) {
        this.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: task.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}
