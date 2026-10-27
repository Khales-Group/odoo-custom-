import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # "Create Bill When Paid" starts ticked on the accounting / finance
    # departments (matched on name); adjust under Approvals > Departments.
    cr.execute("""
        UPDATE kh_approvals_department
           SET kh_auto_bill = TRUE
         WHERE name ILIKE '%%account%%' OR name ILIKE '%%financ%%'
            OR name ILIKE '%%محاسب%%' OR name ILIKE '%%مالي%%'
     RETURNING name
    """)
    _logger.info("kh_approvals: 'Create Bill When Paid' ticked on %s", [row[0] for row in cr.fetchall()])
