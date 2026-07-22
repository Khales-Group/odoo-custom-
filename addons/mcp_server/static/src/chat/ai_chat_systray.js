/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { Component, useState, useRef, onWillStart, onPatched } from "@odoo/owl";

const MAX_FILE_MB = 8;
const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

export class AiChatSystray extends Component {
    static template = "mcp_server.AiChatSystray";
    static props = {};

    setup() {
        this.userInitial = (user.name || "?").trim().charAt(0).toUpperCase() || "?";
        this.state = useState({
            open: false,
            messages: [],
            input: "",
            loading: false,
            hasAccess: false,
            attachment: null,
        });
        this.bodyRef = useRef("body");
        this.fileInputRef = useRef("fileInput");
        this.textareaRef = useRef("textarea");

        onWillStart(async () => {
            try {
                this.state.hasAccess = await user.hasGroup(
                    "mcp_server.group_mcp_user"
                );
            } catch (error) {
                this.state.hasAccess = false;
            }
            if (this.state.hasAccess) {
                await this.loadHistory();
            }
        });
        onPatched(() => {
            this.scrollToBottom();
            this.resizeTextarea();
        });
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
        this.state.attachment = null;
        try {
            await rpc("/mcp/chat/clear", {});
        } catch (error) {
            // ignore - worst case old history reappears on next reload
        }
    }

    onAttachClick() {
        if (this.fileInputRef.el) {
            this.fileInputRef.el.click();
        }
    }

    async onFileChange(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) {
            return;
        }
        if (file.size > MAX_FILE_BYTES) {
            this.state.messages.push({
                role: "assistant",
                text: `⚠️ "${file.name}" is too large (max ${MAX_FILE_MB} MB).`,
            });
            ev.target.value = "";
            return;
        }
        try {
            const dataUrl = await readFileAsDataURL(file);
            const base64 = String(dataUrl).split(",")[1] || "";
            this.state.attachment = {
                filename: file.name,
                mimetype: file.type,
                data: base64,
            };
        } catch (error) {
            this.state.messages.push({
                role: "assistant",
                text: `⚠️ Could not read "${file.name}".`,
            });
        } finally {
            ev.target.value = "";
        }
    }

    removeAttachment() {
        this.state.attachment = null;
    }

    resizeTextarea() {
        const el = this.textareaRef.el;
        if (!el) {
            return;
        }
        el.style.height = "auto";
        el.style.height = Math.min(el.scrollHeight, 120) + "px";
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onSubmit();
        }
    }

    async onSubmit() {
        const text = this.state.input.trim();
        const attachment = this.state.attachment;
        if ((!text && !attachment) || this.state.loading) {
            return;
        }

        let displayText = text;
        if (attachment) {
            displayText = text ? `${text}\n📎 ${attachment.filename}` : `📎 ${attachment.filename}`;
        }
        this.state.messages.push({ role: "user", text: displayText });
        this.state.input = "";
        this.state.attachment = null;
        this.state.loading = true;

        try {
            const result = await rpc("/mcp/chat/send", { message: text, attachment });

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
