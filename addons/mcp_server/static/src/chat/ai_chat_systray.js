/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { Component, useState, useRef, onPatched } from "@odoo/owl";

export class AiChatSystray extends Component {
    static template = "mcp_server.AiChatSystray";
    static props = {};

    setup() {
        this.state = useState({
            open: false,
            messages: [],
            input: "",
            loading: false,
        });
        this.apiHistory = [];
        this.bodyRef = useRef("body");
        onPatched(() => this.scrollToBottom());
    }

    scrollToBottom() {
        if (this.bodyRef.el) {
            this.bodyRef.el.scrollTop = this.bodyRef.el.scrollHeight;
        }
    }

    toggle() {
        this.state.open = !this.state.open;
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
            const result = await rpc("/mcp/chat/send", {
                message: text,
                messages: this.apiHistory,
            });

            if (result && result.error) {
                this.state.messages.push({ role: "assistant", text: `⚠️ ${result.error}` });
            } else if (result) {
                this.apiHistory = result.messages || [];
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
