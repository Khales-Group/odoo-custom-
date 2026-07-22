/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onWillStart, onPatched } from "@odoo/owl";

export class AiChatSystray extends Component {
    static template = "mcp_server.AiChatSystray";
    static props = {};

    setup() {
        this.user = useService("user");
        this.state = useState({
            open: false,
            messages: [],
            input: "",
            loading: false,
            hasAccess: false,
        });
        this.bodyRef = useRef("body");

        onWillStart(async () => {
            this.state.hasAccess = await this.user.hasGroup(
                "mcp_server.group_mcp_user"
            );
            if (this.state.hasAccess) {
                await this.loadHistory();
            }
        });
        onPatched(() => this.scrollToBottom());
    }

    async loadHistory() {
        try {
            const result = await rpc("/mcp/chat/history", {});
            this.state.messages = (result && result.messages) || [];
        } catch (error) {
            // history is best-effort; a fresh chat still works if this fails
        }
    }

    scrollToBottom() {
        if (this.bodyRef.el) {
            this.bodyRef.el.scrollTop = this.bodyRef.el.scrollHeight;
        }
    }

    toggle() {
        this.state.open = !this.state.open;
    }

    async onClear() {
        this.state.messages = [];
        try {
            await rpc("/mcp/chat/clear", {});
        } catch (error) {
            // ignore - worst case old history reappears on next reload
        }
    }

    async onSubmit() {
        const text = this.state.input.trim();
        if (!text || this.state.loading) {
            return;
        }
        this.state.messages.push({ role: "user", text });
        this.state.input = "";
        this.state.loading = true;

        try {
            const result = await rpc("/mcp/chat/send", { message: text });

            if (result && result.error) {
                this.state.messages.push({ role: "assistant", text: `⚠️ ${result.error}` });
            } else if (result) {
                for (const call of result.tool_calls || []) {
                    this.state.messages.push({
                        role: "tool",
                        text: `🔧 ${call.name}${call.is_error ? " — denied/failed" : ""}`,
                    });
                }
                this.state.messages.push({ role: "assistant", text: result.reply });
            }
        } catch (error) {
            this.state.messages.push({
                role: "assistant",
                text: "⚠️ Connection error. Please try again.",
            });
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("systray").add(
    "mcp_server.AiChatSystray",
    { Component: AiChatSystray },
    { sequence: 1 }
);
