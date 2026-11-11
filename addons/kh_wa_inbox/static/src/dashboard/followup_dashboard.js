/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillStart, onWillUnmount, useExternalListener, useState } from "@odoo/owl";
import { dubaiToday, formatLongDay } from "./dates";

/**
 * لوحة المتابعة: a sidebar and a main area, shared by follow-up parts.
 * A module adds a part with
 *
 *     registry.category("kh_followup_dashboard_sections").add("key", {
 *         title: "…",                       // its heading in the sidebar
 *         makeStore: (services) => store,   // services: orm, action, notification
 *         Sidebar: Component,               // props: store, partKey, active, frame
 *         Main: Component,                  // props: store, frame
 *     }, { sequence: 10 });
 *
 * The store is shared by the part's two components. The frame calls
 * store.load({ date, search }) at start, every 60 seconds and when the day
 * or the search change, and reads store.heading ({ title, count, sub }) for
 * the top bar and store.headerNote ({ text, level, alert }) for the foot of
 * the sidebar. A part's Sidebar calls frame.open(partKey) when the user
 * picks one of its entries.
 */
export const DASHBOARD_SECTIONS = "kh_followup_dashboard_sections";
const REFRESH_MS = 60 * 1000;
const SEARCH_DELAY_MS = 350;

export class FollowupDashboard extends Component {
    static template = "kh_wa_inbox.FollowupDashboard";
    static props = ["*"];

    setup() {
        const services = {
            orm: useService("orm"),
            action: useService("action"),
            notification: useService("notification"),
        };
        this.parts = registry
            .category(DASHBOARD_SECTIONS)
            .getEntries()
            .map(([key, part]) => {
                const store = part.makeStore(services);
                return { key, part, store, view: useState(store) };
            });
        // Opened on a given list (the activity menu asks for «بانتظار قرارك»):
        // context { kh_dashboard_part, kh_dashboard_view }.
        const context = (this.props.action && this.props.action.context) || {};
        const start = this.parts.find((part) => part.key === context.kh_dashboard_part);
        if (start && context.kh_dashboard_view && start.store.navigate) {
            start.store.navigate(context.kh_dashboard_view);
        }
        this.state = useState({
            active: start ? start.key : this.parts.length ? this.parts[0].key : null,
            date: null, // null = today
            search: "", // what the parts search for (after a short pause)
            searchInput: "",
            drawer: false, // phone: the sidebar is open
        });
        // What the parts get to talk to the frame.
        this.frame = {
            open: (partKey) => {
                this.state.active = partKey;
                this.state.drawer = false;
                if (this.state.search) {
                    this.clearSearch();
                }
            },
        };
        this.onVisibilityChange = () => {
            if (!document.hidden) {
                this.reload();
            }
        };
        useExternalListener(window, "keydown", (ev) => {
            if (ev.key === "Escape" && this.state.drawer) {
                this.state.drawer = false;
            }
        });
        onWillStart(() => this.reload());
        onMounted(() => {
            this.timer = setInterval(() => !document.hidden && this.reload(), REFRESH_MS);
            document.addEventListener("visibilitychange", this.onVisibilityChange);
        });
        onWillUnmount(() => {
            clearInterval(this.timer);
            clearTimeout(this.searchTimer);
            document.removeEventListener("visibilitychange", this.onVisibilityChange);
        });
    }

    reload() {
        const query = { date: this.state.date, search: this.state.search };
        return Promise.all(this.parts.map((part) => part.view.load(query)));
    }

    get activePart() {
        return this.parts.find((part) => part.key === this.state.active);
    }

    get heading() {
        const part = this.activePart;
        return (part && part.view.heading) || { title: "لوحة المتابعة" };
    }

    get notes() {
        return this.parts.map((part) => part.view.headerNote).filter(Boolean);
    }

    get today() {
        return dubaiToday();
    }

    get pageDate() {
        return formatLongDay(this.state.date || this.today);
    }

    openDrawer() {
        this.state.drawer = true;
    }

    closeDrawer() {
        this.state.drawer = false;
    }

    onDateChange(ev) {
        const value = ev.target.value;
        this.state.date = value && value !== this.today ? value : null;
        this.reload();
    }

    backToToday() {
        this.state.date = null;
        this.reload();
    }

    onSearchInput(ev) {
        this.state.searchInput = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => {
            this.state.search = this.state.searchInput.trim();
            this.reload();
        }, SEARCH_DELAY_MS);
    }

    clearSearch() {
        clearTimeout(this.searchTimer);
        this.state.searchInput = "";
        this.state.search = "";
        this.reload();
    }
}

registry.category("actions").add("kh_followup_dashboard", FollowupDashboard);
