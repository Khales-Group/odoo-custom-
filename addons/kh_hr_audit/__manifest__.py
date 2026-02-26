{
    'name': 'Smart HR Audit',
    'version': '1.0',
    'summary': 'Analyze attendance, deductions, and payroll',
    'sequence': 10,
    'description': """Smart HR Control Center for Attendance & Payroll""",
    'category': 'Human Resources',
    'website': 'https://www.khales.ae',
    'depends': ['base', 'hr', 'hr_attendance', 'hr_payroll', 'hr_holidays'], # تأكد أن الموديولات المعتمدة صحيحة
    'data': [
        'security/ir.model.access.csv',
        'ir_cron_data.xml',
        'views/audit_view.xml',
        'views/hr_audit_views.xml',
    ],
    
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++
    #  هذا هو السطر السحري اللي يخليه يظهر في الشاشة الرئيسية
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++
    'application': True, 
    'installable': True,
    'auto_install': False,
    
    # مسار الأيقونة (اختياري هنا، لأن Odoo يبحث عنها تلقائياً في static/description)
    # 'icon': '/kh_hr_audit/static/description/icon.png', 
}