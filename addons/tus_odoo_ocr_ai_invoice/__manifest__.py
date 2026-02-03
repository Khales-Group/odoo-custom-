# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Odoo OCR Using AI - Invoices & Bills',
    'version': '19.0.1.0.0',
    'summary': """
                Leverage the power of AI and Optical Character Recognition (OCR) in Odoo to automate and streamline your invoice processing. This advanced solution uses cutting-edge AI technology to accurately extract and process data from invoices, reducing manual data entry and minimizing errors. Enhance your financial workflows and increase efficiency with Odoo AI-driven OCR capabilities.
                Odoo OCR AI
                AI-based OCR in Odoo
                Odoo OCR integration
                Odoo OCR document processing
                Odoo AI text recognition
                Odoo OCR AI implementation
                Intelligent OCR Odoo
                Automated OCR Odoo
                Odoo OCR solution
                AI OCR Odoo application
                Odoo OCR AI technology
                Optical Character Recognition
                Odoo OCR
                AI-Driven OCR
                AI Document Processing
                OCR AI Integration
                OCR Invoice & Bills
                OCR Sale Order
                OCR Purchase Order
                OCR Expense
                """,
    'sequence': 10,
    'description': """
        Leverage the power of AI and Optical Character Recognition (OCR) in Odoo to automate 
        and streamline your invoice processing. This advanced solution uses cutting-edge 
        AI technology to accurately extract and process data from invoices, reducing manual 
        data entry and minimizing errors. Enhance your financial workflows and increase efficiency
        with Odoo's AI-driven OCR capabilities.""",
    'category': 'Accounting',
    'website': "https://www.techultrasolutions.com",
    "author": "TechUltra Solutions Private Limited",
    "company": "TechUltra Solutions Private Limited",
    'live_test_url': 'https://ai.fynix.app/',
    'depends': ["account", "tus_odoo_ocr_ai_base"],
    'data': [
        'data/ocr_model_data.xml',
        'views/account_move_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tus_odoo_ocr_ai_invoice/static/src/xml/**/*',
            'tus_odoo_ocr_ai_invoice/static/src/js/**/*',
        ],
    },
    "images": ["static/description/main_banner.gif"],
    'installable': True,
    'application': True,

    'license': 'OPL-1',
}
