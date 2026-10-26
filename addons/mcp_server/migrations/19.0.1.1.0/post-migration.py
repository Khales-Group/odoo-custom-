def migrate(cr, version):
    # The Anthropic account ran out of credit (Oct 2026): switch the
    # in-system chat to Gemini, which uses the gemini.api.key system
    # parameter already set for kh_ai_backport. Switch back any time under
    # Settings > MCP Server > Chat Provider.
    cr.execute("""
        INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date)
        VALUES ('mcp_server.chat_provider', 'gemini', 1, now() at time zone 'UTC', 1, now() at time zone 'UTC')
        ON CONFLICT (key) DO UPDATE SET value = 'gemini', write_date = now() at time zone 'UTC'
    """)
