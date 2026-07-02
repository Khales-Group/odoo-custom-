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
      lastText: "",
    });
    this._mediaRecorder = null;
    this._audioChunks = [];
  },

  async onVoiceStart() {
    this.voiceState.error = "";
    this.voiceState.lastText = "";
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
        this.voiceState.lastText = result.text;
        this._insertText(result.text);
      } else {
        this.voiceState.error = "لم يُكتشف نص";
      }
    } catch {
      this.voiceState.error = "فشل التحويل، حاول مجدداً";
    } finally {
      this.voiceState.processing = false;
    }
  },

  // Called from chip button via t-on-mousedown.prevent
  onInsertLastText(ev) {
    ev.preventDefault(); // keep editor focus
    if (this.voiceState.lastText) {
      this._insertText(this.voiceState.lastText);
    }
  },

  _insertText(text) {
    // Mirror exactly how addEmoji() works in Composer (Odoo 19 source)
    if (this.editor) {
      // WYSIWYG html_editor path
      this.editor.shared.dom.insert(text);
      this.editor.shared.history.addStep();
    } else {
      // Plain-text path (same fallback as addEmoji)
      const composerText = this.props.composer.composerText || "";
      const start = this.props.composer.selection?.start ?? composerText.length;
      const end = this.props.composer.selection?.end ?? composerText.length;
      const before = composerText.slice(0, start);
      const after = composerText.slice(end);
      const sep = before && !/\s$/.test(before) ? " " : "";
      this.props.composer.composerText = before + sep + text + after;
      this.selection?.moveCursor?.((before + sep + text).length);
    }
    // Re-focus the composer — addEmoji does this too, critical!
    this.props.composer.autofocus++;
  },
});
