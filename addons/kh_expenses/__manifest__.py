{
    "name": "Khales Expenses",
    "version": "19.0.1.0.0",
    "summary": "Company expenses to pay (rent, employee expenses, water and electricity, fees), with manager approval",
    "description": """
Khales Expenses
===============

The same idea as the Collection app, for money the company has to pay:
rent, employee expenses, water and electricity, government fees and other
expenses.

Each expense has an amount, what was paid and what remains, a due date and
the accountant who handles it. The accountant asks for payment approval,
Majed approves (or rejects) it, then the accountant marks it paid. A monthly
expense (rent, water...) creates next month's expense when it is paid.

Menus: Expenses (all), Overdue, By Employee (employee expenses per employee)
and By Type, with Amount / Paid / Remaining totals.
    """,
    "author": "Khales Group",
    "category": "Accounting",
    "depends": ["mail", "hr", "project"],
    "data": [
        "security/kh_expenses_security.xml",
        "security/ir.model.access.csv",
        "views/kh_expense_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
