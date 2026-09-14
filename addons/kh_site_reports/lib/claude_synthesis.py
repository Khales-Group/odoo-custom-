import json

DEFAULT_MODEL = "claude-sonnet-4-6"

MONTHLY_SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "site_update_summary": {
            "type": "string",
            "description": (
                "Concise summary (4-6 sentences total) of construction progress across ALL the visits "
                "this month, for a client-facing report. Synthesize across visits rather than restating "
                "each one."
            ),
        },
        "planned_activities": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "3-5 short bullet points of logical next steps for next month, inferred from what is "
                "complete/in-progress in the notes (e.g. if blockwork just finished, next is likely "
                "roofing/waterproofing). Do not invent specific dates or numbers not implied by the notes."
            ),
        },
        "recommendations": {
            "type": "string",
            "description": (
                "2-4 sentences on any decisions, approvals, or payments that appear to be needed from the "
                "owner based on the notes. If nothing specific stands out, say there are no outstanding "
                "owner actions this period rather than inventing one."
            ),
        },
    },
    "required": ["site_update_summary", "planned_activities", "recommendations"],
    "additionalProperties": False,
}


def synthesize_monthly_report(client, model, project_name, visits, language="en"):
    """visits: list of {"date_label": str, "narrative": str}.
    Mirrors site-report-generator.js's synthesizeMonthlyReport: one cheap
    text-only Claude call combining the already-AI-written per-visit notes
    (posted by project-watcher.js) into a client-facing synthesis.

    language: "en" or "ar" — controls the language of the generated text
    (the JSON field names stay fixed per MONTHLY_SYNTHESIS_SCHEMA either way).
    """
    combined = "\n\n".join(f"{v['date_label']}:\n{v['narrative']}" for v in visits)
    if language == "ar":
        language_instruction = (
            "Write your entire response in formal Modern Standard Arabic, in a client-facing "
            "construction-report tone. Keep the JSON field names in English exactly as given by the "
            "schema — only the text VALUES must be in Arabic."
        )
    else:
        language_instruction = "Write your entire response in English."
    prompt = (
        f'Here are the site-visit update notes already written for "{project_name}" this reporting period '
        f"(one per visit, already AI-summarized from site photos):\n\n{combined}\n\n"
        "Produce a client-facing monthly report synthesis from these notes only — do not assume anything "
        f"not stated in them. {language_instruction}"
    )
    resp = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=1200,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": MONTHLY_SYNTHESIS_SCHEMA},
        },
        messages=[{"role": "user", "content": prompt}],
    )
    text_block = next((b for b in resp.content if b.type == "text"), None)
    if text_block is None:
        raise ValueError("No text content in Claude monthly-synthesis response")
    return json.loads(text_block.text)
