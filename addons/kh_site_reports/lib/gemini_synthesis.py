import json

DEFAULT_MODEL = "gemini-3.6-flash"

LOCALIZE_FIELDS = [
    "project_name", "location", "contractor", "consultant",
    "client_name", "manager_name", "plot_number",
]

LOCALIZE_INSTRUCTIONS = """
You are preparing the Arabic edition of a construction project's monthly report cover page. Below
are raw field values pulled directly from the project's database record as JSON. Some of them have
a redundant English label baked into the value itself (e.g. a contractor field literally containing
"contractor:  ACME Co", or a plot number field containing "plot number: 410 F") because of how the
data was originally entered; some are personal or company names written in Latin script that need a
natural Arabic rendering rather than a literal word-for-word translation.

For EACH field, return its Arabic-ready value:
- Strip any redundant English label prefix that duplicates the field's own meaning — this report
  already shows its own Arabic label right next to the value, so do not repeat it.
- Transliterate personal and company names into natural, correctly-spelled Arabic script (do not
  translate a name's *meaning* — transliterate its sound).
- Translate place names into their standard Arabic name.
- Keep alphanumeric codes (like a plot number "410 F") exactly as-is, only stripping the redundant
  label text around them.
- For "project_name" specifically: this report's own template already prefixes it with the word
  "مشروع" wherever it's used, so do NOT start your Arabic rendering with "مشروع" yourself — just
  translate the distinguishing part of the name (e.g. the client's name), dropping filler like "'s
  opportunity" or a leading numeric reference code.
- If a field is empty or you cannot confidently render it, return it unchanged.

Return a single JSON object with exactly these keys, each mapped to its Arabic-ready string value:
{fields}
Return ONLY the JSON object, with no markdown fences and no other text.

Raw values:
{raw_json}
"""

SYNTHESIS_INSTRUCTIONS = """
Respond with a single JSON object with exactly these three keys:
- "site_update_summary": string — concise summary (4-6 sentences total) of construction progress across ALL the visits this month, for a client-facing report. Synthesize across visits rather than restating each one.
- "planned_activities": array of strings — 3-5 short bullet points of logical next steps for next month, inferred from what is complete/in-progress in the notes (e.g. if blockwork just finished, next is likely roofing/waterproofing). Do not invent specific dates or numbers not implied by the notes.
- "recommendations": string — 2-4 sentences on any decisions, approvals, or payments that appear to be needed from the owner based on the notes. If nothing specific stands out, say there are no outstanding owner actions this period rather than inventing one.
Return ONLY the JSON object, with no markdown fences and no other text.
"""


def _generate_json(client, model, prompt, temperature):
    from google.genai import types

    resp = client.models.generate_content(
        model=model or DEFAULT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature, response_mime_type="application/json"),
    )

    text = resp.text
    if not text and resp.candidates:
        text = "".join(getattr(part, "text", "") or "" for part in resp.candidates[0].content.parts)
    if not text:
        raise ValueError("No text content in Gemini response")

    return json.loads(text)


def synthesize_monthly_report(client, model, project_name, visits, language="en"):
    """visits: list of {"date_label": str, "narrative": str}.
    One cheap text-only Gemini call combining the already-AI-written per-visit notes
    (posted by project-watcher.js) into a client-facing synthesis.

    language: "en" or "ar" — controls the language of the generated text
    (the JSON keys themselves stay fixed in English either way).
    """
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

    return _generate_json(client, model, prompt, temperature=0.3)


def localize_project_meta(client, model, project_meta):
    """project_meta: the dict built in project_project.py (project_no, project_name,
    location, contractor, consultant, client_name, plot_number, manager_name).

    Returns a copy of project_meta with the human-facing fields (LOCALIZE_FIELDS)
    replaced by Gemini's Arabic-ready rendering — natural transliteration of names,
    translation of place names, and stripped-out redundant English label prefixes
    that some of these Odoo Studio fields bake into their raw value. Fields Gemini
    can't confidently handle, or that come back empty, are left as in the input.
    """
    raw = {key: project_meta.get(key) or "" for key in LOCALIZE_FIELDS}
    prompt = LOCALIZE_INSTRUCTIONS.format(
        fields=", ".join(f'"{key}"' for key in LOCALIZE_FIELDS),
        raw_json=json.dumps(raw, ensure_ascii=False),
    )

    localized = _generate_json(client, model, prompt, temperature=0.2)

    merged = dict(project_meta)
    for key in LOCALIZE_FIELDS:
        value = localized.get(key)
        if value:
            merged[key] = value
    return merged
