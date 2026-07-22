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

export class AiChatPage extends Component {
    static template = "mcp_server.AiChatPage";
    static props = ["*"];

    setup() {
        this.userInitial = (user.name || "?").trim().charAt(0).toUpperCase() || "?";
        this.state = useState({
            conversations: [],
            conversationId: null,
            messages: [],
            input: "",
            loading: false,
            attachment: null,
        });
        this.bodyRef = useRef("body");
        this.fileInputRef = useRef("fileInput");
        this.textareaRef = useRef("textarea");

        onWillStart(() => this.loadConversations());
        onPatched(() => {
            this.scrollToBottom();
            this.resizeTextarea();
        });
    }

    async loadConversations() {
        try {
            const result = await rpc("/mcp/chat/conversations", {});
            this.state.conversations = (result && result.conversations) || [];
        } catch (error) {
            this.state.conversations = [];
        }
    }

    async selectConversation(id) {
        if (this.state.conversationId === id) {
            return;
        }
        this.state.conversationId = id;
        this.state.messages = [];
        this.state.attachment = null;
        try {
            const result = await rpc("/mcp/chat/history", { conversation_id: id });
            this.state.messages = (result && result.messages) || [];
        } catch (error) {
            // leave empty on failure
        }
    }

    onNewChat() {
        this.state.conversationId = null;
        this.state.messages = [];
        this.state.attachment = null;
    }

    async onDeleteConversation(id, ev) {
        ev.stopPropagation();
        try {
            await rpc("/mcp/chat/conversation/delete", { conversation_id: id });
        } catch (error) {
            // ignore - list refresh below will simply still show it once
        }
        if (this.state.conversationId === id) {
            this.onNewChat();
        }
        await this.loadConversations();
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
        el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }

    scrollToBottom() {
        if (this.bodyRef.el) {
            this.bodyRef.el.scrollTop = this.bodyRef.el.scrollHeight;
        }
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
            displayText = text
                ? `${text}\n📎 ${attachment.filename}`
                : `📎 ${attachment.filename}`;
        }
        this.state.messages.push({ role: "user", text: displayText });
        this.state.input = "";
        this.state.attachment = null;
        this.state.loading = true;

        try {
            const result = await rpc("/mcp/chat/send", {
                message: text,
                attachment,
                conversation_id: this.state.conversationId,
            });

            if (result && result.error) {
                this.state.messages.push({ role: "assistant", text: `⚠️ ${result.error}` });
            } else if (result) {
                this.state.conversationId = result.conversation_id || this.state.conversationId;
                for (const call of result.tool_calls || []) {
                    this.state.messages.push({
                        role: "tool",
                        text: `🔧 ${call.name}${call.is_error ? " — denied/failed" : ""}`,
                    });
                }
                this.state.messages.push({ role: "assistant", text: result.reply });
                await this.loadConversations();
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

registry.category("actions").add("mcp_server.ai_chat_action", AiChatPage);
