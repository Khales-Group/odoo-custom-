/** @odoo-module **/

import { Composer } from "@mail/core/common/composer";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

patch(Composer.prototype, {
    setup() {
        super.setup();
        this.rpc = useService("rpc");
        this.voiceState = useState({
            recording: false,
            processing: false,
            error: "",
        });
        this._mediaRecorder = null;
        this._audioChunks = [];
    },

    async onVoiceStart() {
        this.voiceState.error = "";
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this._audioChunks = [];

            const mimeType =
                ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find(
                    (t) => MediaRecorder.isTypeSupported(t)
                ) || "audio/webm";

            this._mediaRecorder = new MediaRecorder(stream, { mimeType });
            this._mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) this._audioChunks.push(e.data);
            };
            this._mediaRecorder.onstop = () => {
                stream.getTracks().forEach((t) => t.stop());
                this._processAudio(mimeType.split(";")[0]);
            };
            this._mediaRecorder.start();
            this.voiceState.recording = true;
        } catch {
            this.voiceState.error = "تعذّر الوصول للمايكروفون";
        }
    },

    onVoiceStop() {
        if (this._mediaRecorder && this.voiceState.recording) {
            this._mediaRecorder.stop();
            this.voiceState.recording = false;
            this.voiceState.processing = true;
        }
    },

    async _processAudio(mimeType) {
        try {
            const blob = new Blob(this._audioChunks, { type: mimeType });
            const base64 = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result.split(",")[1]);
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            });

            const result = await this.rpc("/kh/voice/transcribe", {
                audio_data: base64,
                mime_type: mimeType,
            });

            if (result.error) {
                this.voiceState.error = result.error;
            } else if (result.text) {
                this._insertText(result.text);
            }
        } catch {
            this.voiceState.error = "فشل التحويل، حاول مجدداً";
        } finally {
            this.voiceState.processing = false;
        }
    },

    _insertText(text) {
        const el = this.el;
        if (!el) return;

        // Simple textarea (log note plain mode)
        const ta = el.querySelector("textarea");
        if (ta) {
            const pos = ta.selectionStart != null ? ta.selectionStart : ta.value.length;
            const before = ta.value.slice(0, pos);
            const after = ta.value.slice(pos);
            const sep = before && !/\s$/.test(before) ? " " : "";
            ta.value = before + sep + text + after;
            const newPos = pos + sep.length + text.length;
            ta.setSelectionRange(newPos, newPos);
            ta.dispatchEvent(new Event("input", { bubbles: true }));
            ta.focus();
            return;
        }

        // Richtext / wysiwyg editor
        const ed = el.querySelector("[contenteditable='true']");
        if (ed) {
            ed.focus();
            const sel = window.getSelection();
            if (sel && !sel.rangeCount) {
                const range = document.createRange();
                range.selectNodeContents(ed);
                range.collapse(false);
                sel.removeAllRanges();
                sel.addRange(range);
            }
            document.execCommand("insertText", false, text);
        }
    },
});
