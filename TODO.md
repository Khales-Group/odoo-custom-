# TODO: Update Gemini SDK to New Google GenAI SDK

## Changes Required:

### 1. Update Controller (addons/kh_ai_backport/controllers/ai_override.py)

- [x] Change import to try `from google import genai` (new SDK) first
- [ ] Remove the old SDK usage logic (the `elif hasattr(genai, 'configure')` block)
- [ ] Use only the new SDK pattern with `client.models.generate_content()`

### 2. Update Model (addons/kh_ai_backport/models/ai_agent.py)

- [ ] Change import to `from google import genai`
- [ ] Replace `genai.configure()` + `GenerativeModel` with `genai.Client`
- [ ] Use `client.models.generate_content(model="gemini-2.0-flash", contents=prompt)`
- [ ] Use `getattr(response, "text", str(response))` for safety

## Status:

- [ ] Task Completed
