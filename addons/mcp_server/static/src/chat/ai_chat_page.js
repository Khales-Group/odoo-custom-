/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { markdownToHtml } from "./markdown";
import { Component, useState, useRef, onWillStart, onPatched, markup } from "@odoo/owl";

const MAX_FILE_MB = 8;
const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;
const MAX_ATTACHMENTS = 5;

function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

const FILE_ICONS = {
    pdf: "fa-file-pdf-o",
    doc: "fa-file-word-o",
    docx: "fa-file-word-o",
    xls: "fa-file-excel-o",
    xlsx: "fa-file-excel-o",
    ppt: "fa-file-powerpoint-o",
    pptx: "fa-file-powerpoint-o",
};

function fileIconClass(filename) {
    const ext = String(filename || "").split(".").pop().toLowerCase();
    return FILE_ICONS[ext] || "fa-file-o";
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
            attachments: [],
            sidebarOpen: false,
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
        this.state.sidebarOpen = false;
        if (this.state.conversationId === id) {
            return;
        }
        this.state.conversationId = id;
        this.state.messages = [];
        this.state.attachments = [];
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
        this.state.attachments = [];
        this.state.sidebarOpen = false;
    }

    toggleSidebar() {
        this.state.sidebarOpen = !this.state.sidebarOpen;
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
        const files = Array.from(ev.target.files || []);
        if (!files.length) {
            return;
        }

        for (const file of files) {
            if (this.state.attachments.length >= MAX_ATTACHMENTS) {
                this.state.messages.push({
                    role: "assistant",
                    text: `⚠️ You can attach up to ${MAX_ATTACHMENTS} files per message.`,
                });
                break;
            }
            if (file.size > MAX_FILE_BYTES) {
                this.state.messages.push({
                    role: "assistant",
                    text: `⚠️ "${file.name}" is too large (max ${MAX_FILE_MB} MB).`,
                });
                continue;
            }
            try {
                const dataUrl = await readFileAsDataURL(file);
                const base64 = String(dataUrl).split(",")[1] || "";
                this.state.attachments.push({
                    filename: file.name,
                    mimetype: file.type,
                    data: base64,
                });
            } catch (error) {
                this.state.messages.push({
                    role: "assistant",
                    text: `⚠️ Could not read "${file.name}".`,
                });
            }
        }
        ev.target.value = "";
    }

    removeAttachment(index) {
        this.state.attachments.splice(index, 1);
    }

    renderMarkdown(text) {
        return markup(markdownToHtml(text || ""));
    }

    getFileIcon(filename) {
        return fileIconClass(filename);
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
        const attachments = this.state.attachments;
        if ((!text && !attachments.length) || this.state.loading) {
            return;
        }

        let displayText = text;
        if (attachments.length) {
            const names = attachments.map((a) => `📎 ${a.filename}`).join("\n");
            displayText = text ? `${text}\n${names}` : names;
        }
        this.state.messages.push({ role: "user", text: displayText });
        this.state.input = "";
        this.state.attachments = [];
        this.state.loading = true;

        try {
            const result = await rpc("/mcp/chat/send", {
                message: text,
                attachments,
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
                this.state.messages.push({
                    role: "assistant",
                    text: result.reply,
                    files: result.files || [],
                });
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
