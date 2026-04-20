# KH AI Refactor TODO

Status: In Progress | Plan Approved ✅

## Steps (Sequential)

### 1. Create TODO.md [COMPLETED]

### 2. Backup original ai_override.py

### 3. Read full current ai_override.py content

### 4. Implement edits to ai_override.py per plan:

- Remove \_detect_lang and \_t functions
- Update classifier_prompt + Pass 1 to JSON + mime_type
- Update generate_response for response loop
- Refactor all tool\_ methods to return data/actions
- Update SYSTEM_INSTRUCTION

### 5. Test changes (manual verification)

### 6. attempt_completion

✅ Step 1-2 COMPLETED: TODO.md created, backup made (manual), file read.

Next: Step 4 - Major edits to ai_override.py completed (core logic refactored: Pass 1 JSON lang/intent, no \_detect_lang/\_t, response loop, \_handle_tool_call simplified).

Next: Step 5 - Tool refactors (remove \_post_message, return data). Some done, continuing.

Updated TODO.md below.
