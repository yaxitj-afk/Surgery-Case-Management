# -*- coding: utf-8 -*-
{  # App information
    'name': 'Surgery Case Management',
    'category': 'Healthcare',
    'version': '19.0.1.0',
    'sequence': 1,
    'summary': """""",

    'description': """""",
    'license': 'OPL-1',

    # Dependencies
    'depends': ['base','mail','sms','sign','project','account','documents', 'drcolle_hospital_invoicing'],

    # Views
    'data': [
        'security/ir.model.access.csv',
        'wizard/admission_wizard_views.xml',
        'report/admission_document_report.xml',
        "report/hospital_invoice_report.xml",
        'data/demo_view.xml',
        'data/cron.xml',
        'views/surgery_prcedure_view.xml',
        'views/surgery_case_views.xml',
        'views/surgery_menus.xml',
        'views/res_partner_view.xml',
        'views/res_config_settings_views.xml',
        'views/operating_block_views.xml',
        'views/res_users_views.xml',
        'views/clinic_postop_followup_views.xml',
        'views/admission_view.xml',
        'views/surgery_dashboard_actions.xml',
    ],

    'assets': {'web.assets_backend': [
                # OWL template for the calendar widget
                'surgery_case_management/static/src/xml/surgery_date_picker.xml',
                'surgery_case_management/static/src/xml/timeslot_widget.xml',
                'surgery_case_management/static/src/xml/surgery_dashboard.xml',
                # JS widget
                'surgery_case_management/static/src/js/timeslot_widget.js',
                'surgery_case_management/static/src/js/surgery_date_picker.js',
                'surgery_case_management/static/src/js/surgery_dashboard.js',
                # SCSS styles
                'surgery_case_management/static/src/scss/surgery_date_picker.scss',
                'surgery_case_management/static/src/scss/surgery_dashboard.scss',
            ],
    },


    # Odoo Store Specific
    'images': [],

    # Author
    'author': 'Vraja Technologies',
    'website': 'http://www.vrajatechnologies.com',
    'maintainer': 'Vraja Technologies',
    'live_test_url': 'https://www.vrajatechnologies.com/contactus',

    # Technical
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': '',
    'currency': 'EUR',
}
