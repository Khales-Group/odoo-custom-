/** @odoo-module **/
import { Composer } from "@mail/components/composer/composer";
import { patch } from "@web/core/utils/patch";

// نقوم بترقيع مكون الـ Composer لإجبار أودو على إظهار زر الملفات للـ AI
patch(Composer.prototype, "kh_ai_backport.ComposerAI", {
  /**
   * @override
   */
  get hasFileSupport() {
    // إذا كانت المحادثة موجهة لوكيل ذكاء اصطناعي، نُفعل دعم الملفات
    if (this.props.thread && this.props.thread.model === "ai.agent") {
      return true;
    }
    return super.hasFileSupport;
  },

  /**
   * @override
   */
  get isSendButtonDisabled() {
    // التأكد من أن زر الإرسال يعمل حتى عند وجود مرفقات
    return super.isSendButtonDisabled;
  },
});
