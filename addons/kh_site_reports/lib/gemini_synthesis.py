import json

DEFAULT_MODEL = "gemini-3.6-flash"

SYNTHESIS_INSTRUCTIONS = """
Respond with a single JSON object with exactly these three keys:
- "site_update_summary": string — concise summary (4-6 sentences total) of construction progress across ALL the visits this month, for a client-facing report. Synthesize across visits rather than restating each one.
- "planned_activities": array of strings — 3-5 short bullet points of logical next steps for next month, inferred from what is complete/in-progress in the notes (e.g. if blockwork just finished, next is likely roofing/waterproofing). Do not invent specific dates or numbers not implied by the notes.
- "recommendations": string — 2-4 sentences on any decisions, approvals, or payments that appear to be needed from the owner based on the notes. If nothing specific stands out, say there are no outstanding owner actions this period rather than inventing one.
Return ONLY the JSON object, with no markdown fences and no other text.
"""


def synthesize_monthly_report(client, model, project_name, visits, language="en"):
    """visits: list of {"date_label": str, "narrative": str}.
    One cheap text-only Gemini call combining the already-AI-written per-visit notes
    (posted by project-watcher.js) into a client-facing synthesis.

    language: "en" or "ar" — controls the language of the generated text
    (the JSON keys themselves stay fixed in English either way).
    """
    from google.genai import types

    combined = "\n\n".join(f"{v['date_label']}:\n{v['narrative']}" for v in visits)
    if language == "ar":
        language_instruction = (
            "Write your entire response in formal Modern Standard Arabic, in a client-facing "
            "construction-report tone. Keep the JSON keys in English exactly as specified below — "
            "only the text VALUES must be in Arabic."
        )
    else:
        language_instruction = "Write your entire response in English."

    prompt = (
        f'Here are the site-visit update notes already written for "{project_name}" this reporting period '
        f"(one per visit, already AI-summarized from site photos):\n\n{combined}\n\n"
        "Produce a client-facing monthly report synthesis from these notes only — do not assume anything "
        f"not stated in them. {language_instruction}\n\n{SYNTHESIS_INSTRUCTIONS}"
    )

    resp = client.models.generate_content(
        model=model or DEFAULT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3, response_mime_type="application/json"),
    )

    text = resp.text
    if not text and resp.candidates:
        text = "".join(getattr(part, "text", "") or "" for part in resp.candidates[0].content.parts)
    if not text:
        raise ValueError("No text content in Gemini monthly-synthesis response")

    return json.loads(text)
