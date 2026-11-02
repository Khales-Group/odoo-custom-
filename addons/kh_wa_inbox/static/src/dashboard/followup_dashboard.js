/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { dubaiToday, formatLongDay } from "./dates";

/**
 * لوحة المتابعة: a frame for follow-up parts. A module adds a part with
 *
 *     registry.category("kh_followup_dashboard_sections").add("key", {
 *         component: MyPart,   // gets date, search, tick, setHeaderNote
 *         title: "…",          // shown above the part (optional)
 *     }, { sequence: 10 });
 *
 * The frame owns the header (title, today's date, the day picker, search)
 * and a 60-second refresh tick. Each part loads its own data when date,
 * search or tick change, and can put a line in the header with
 * setHeaderNote(key, { text, level: "ok" | "warn" | "late", alert }).
 */
export const DASHBOARD_SECTIONS = "kh_followup_dashboard_sections";
const REFRESH_MS = 60 * 1000;
const SEARCH_DELAY_MS = 350;

export class FollowupDashboard extends Component {
    static template = "kh_wa_inbox.FollowupDashboard";
    static props = ["*"];

    setup() {
        this.sections = registry.category(DASHBOARD_SECTIONS).getEntries();
        this.state = useState({
            date: null, // null = today
            search: "", // what the parts search for (after a short pause)
            searchInput: "",
            tick: 0,
            notes: {},
        });
        this.setHeaderNote = (key, note) => {
            const current = this.state.notes[key];
            const same = current && note && ["text", "level", "alert"].every((k) => current[k] === note[k]);
            if (!same) {
                this.state.notes[key] = note;
            }
        };
        this.onVisibilityChange = () => {
            if (!document.hidden) {
                this.refresh();
            }
        };
        onMounted(() => {
            this.timer = setInterval(() => {
                if (!document.hidden) {
                    this.refresh();
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

    get today() {
        return dubaiToday();
    }

    get pageDate() {
        return formatLongDay(this.state.date || this.today);
    }

    get notes() {
        return Object.values(this.state.notes).filter(Boolean);
    }

    refresh() {
        this.state.tick++;
    }

    onDateChange(ev) {
        const value = ev.target.value;
        this.state.date = value && value !== this.today ? value : null;
    }

    backToToday() {
        this.state.date = null;
    }

    onSearchInput(ev) {
        this.state.searchInput = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => {
            this.state.search = this.state.searchInput.trim();
        }, SEARCH_DELAY_MS);
    }

    clearSearch() {
        clearTimeout(this.searchTimer);
        this.state.searchInput = "";
        this.state.search = "";
    }
}

registry.category("actions").add("kh_followup_dashboard", FollowupDashboard);
