def migrate(cr, version):
    # Unique references from the system, numbered in the order the cases
    # were created (the unique constraint is added when the module loads).
    cr.execute("""
        UPDATE kh_collection_case c
           SET name = 'COL-' || lpad(r.n::text, 5, '0')
          FROM (SELECT id, row_number() OVER (ORDER BY create_date, id) AS n
                  FROM kh_collection_case) r
         WHERE r.id = c.id
    """)
    # No PRO step any more: what the PRO held goes back to the accountant.
    # The cases are remembered for the post-migration (their files, tasks
    # and a note on each case).
    cr.execute("DROP TABLE IF EXISTS kh_collection_pro_moved")
    cr.execute("""
        CREATE TABLE kh_collection_pro_moved AS
        SELECT id FROM kh_collection_case WHERE state IN ('pro', 'pending_pro_approval')
    """)
    cr.execute("""
        DELETE FROM mail_activity
         WHERE res_model = 'kh.collection.case'
           AND summary = 'Approval needed: collection case escalation'
           AND res_id IN (SELECT id FROM kh_collection_case WHERE state = 'pending_pro_approval')
    """)
    cr.execute("UPDATE kh_collection_case SET state = 'accountant' WHERE state IN ('pro', 'pending_pro_approval')")
