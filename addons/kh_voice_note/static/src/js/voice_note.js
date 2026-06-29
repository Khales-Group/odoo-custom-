/** @odoo-module **/

import { Composer } from "@mail/core/common/composer";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

patch(Composer.prototype, {
  setup() {
    super.setup();
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
          (t) => MediaRecorder.isTypeSupported(t),
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

      const result = await rpc("/kh/voice/transcribe", {
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
    // Primary path: Odoo 19 WYSIWYG editor API (same as addEmoji / canned responses)
    if (this.editor) {
      this.editor.shared.dom.insert(text);
      this.editor.shared.history.addStep();
      return;
    }

    // Fallback: plain textarea (non-WYSIWYG context)
    const el = this.el;
    if (!el) return;
    const ta = el.querySelector("textarea");
    if (!ta) return;
    ta.focus();
    const s = ta.selectionStart != null ? ta.selectionStart : ta.value.length;
    const before = ta.value.slice(0, s);
    const after = ta.value.slice(s);
    const sep = before && !/\s$/.test(before) ? " " : "";
    ta.value = before + sep + text + after;
    ta.setSelectionRange(s + sep.length + text.length, s + sep.length + text.length);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    ta.focus();
  },
});
