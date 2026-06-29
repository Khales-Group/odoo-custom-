# -*- coding: utf-8 -*-
import base64
import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


def _call_deepgram(audio_bytes, mime_type, language, api_key):
    url = f"{DEEPGRAM_URL}?model=nova-3&language={language}&punctuate=true"
    req = urllib.request.Request(
        url,
        data=audio_bytes,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": mime_type,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    alt = (
        data.get("results", {})
        .get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
    )
    return {
        "language": language,
        "text": (alt.get("transcript") or "").strip(),
        "confidence": alt.get("confidence") or 0.0,
    }


class VoiceNoteController(http.Controller):

    @http.route("/kh/voice/transcribe", type="json", auth="user", methods=["POST"], csrf=False)
    def transcribe(self, audio_data, mime_type="audio/webm"):
        ICP = request.env["ir.config_parameter"].sudo()
        api_key = ICP.get_param("deepgram.api.key")
        if not api_key:
            return {"error": "deepgram.api.key غير موجود في System Parameters"}

        try:
            audio_bytes = base64.b64decode(audio_data)
        except Exception:
            return {"error": "بيانات الصوت تالفة"}

        results = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(_call_deepgram, audio_bytes, mime_type, lang, api_key): lang
                for lang in ("ar", "en")
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    _logger.warning("Deepgram %s failed: %s", futures[future], exc)

        if not results:
            return {"error": "فشل التحويل لكلا اللغتين"}

        best = max(results, key=lambda r: r["confidence"])

        if not best["text"]:
            return {"error": "لم يُكتشف نص في التسجيل"}

        return {
            "text": best["text"],
            "language": best["language"],
            "confidence": best["confidence"],
        }
