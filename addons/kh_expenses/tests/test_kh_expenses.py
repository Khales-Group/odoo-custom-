from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKhExpenses(TransactionCase):
    def test_approval_then_paid_creates_next_month(self):
        expense = self.env["kh.expense"].create({
            "name": "Office rent",
            "expense_type": "rent",
            "amount": 1000.0,
            "due_date": date(2026, 12, 1),
            "recurring": True,
        })
        self.assertEqual(expense.balance_amount, 1000.0)
        expense.action_request_approval()
        self.assertEqual(expense.state, "pending_approval")
        if self.env.user.id != 369:
            with self.assertRaises(UserError):
                expense.action_approve()
            with self.assertRaises(UserError):
                expense.action_mark_paid()
        expense.state = "approved"
        expense.action_mark_paid()
        self.assertEqual(expense.state, "paid")
        self.assertEqual(expense.balance_amount, 0.0)
        nxt = expense.next_expense_id
        self.assertTrue(nxt)
        self.assertEqual(nxt.due_date, date(2027, 1, 1))
        self.assertEqual((nxt.state, nxt.paid_amount), ("to_pay", 0.0))
