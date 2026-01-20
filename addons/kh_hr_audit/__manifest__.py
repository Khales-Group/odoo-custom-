{
    'name': 'Khales HR Smart Audit',
    'version': '1.0',
    'category': 'Human Resources',
    'summary': 'AI-driven Audit for Attendance, Leaves, and Payroll Automation',
    'author': 'Khales Group',
    'depends': [
        'base', 
        'hr', 
        'hr_attendance', 
        'hr_holidays', 
        'hr_payroll', 
        'mail'
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_jobs.xml',
        'views/audit_view.xml',
        'data/email_template.xml',
    ],
    'installable': True,
    'application': True,
    'sequence': -100,
}