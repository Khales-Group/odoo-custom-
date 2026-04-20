# KH AI Backport - Fix RPC_ERROR Plan

## Step 1: ✅ Complete - Analyzed Error

- **Root Cause**: `_parse_input()` returns 5 values but `generate_response()` unpacks 4
- **File**: `addons/kh_ai_backport/controllers/ai_override.py`
- **Line**: ~525 in `generate_response()`

## Step 2: Plan Approved - Apply Fix

```
OLD (line ~525):
prompt, mail_message_id, chat_history, attachments = self._parse_input(kwargs)

NEW:
prompt, mail_message_id, chat_history, attachments, _ = self._parse_input(kwargs)
```

## Step 3: ✅ Complete - Fixed Unpack Error\n- Changed line 521: added `, _` to match 5-value return\n- Cleaned up duplicate `return {}` syntax\n\n## Step 4: Pending - Test & Deploy\n- Restart Odoo: `./odoo-bin -u kh_ai_backport`\n- Test AI chat: `/web#action=mail.action_discuss`\n- Verify RPC_ERROR gone"

</xai:function_call name="execute_command">
<parameter name="command">echo "Fixed! Restart Odoo server with: cd /path/to/odoo && ./odoo-bin -u kh_ai_backport -d your_db"

## Step 4: Pending - Test

- Restart Odoo: `./odoo-bin -u kh_ai_backport`
- Test AI chat endpoint
- Verify RPC_ERROR resolved

## Step 5: Complete Task

- `attempt_completion`
