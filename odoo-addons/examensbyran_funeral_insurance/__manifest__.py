# -*- coding: utf-8 -*-
{
    'name': 'Examensbyrån Begravningsförsäkring',
    'version': '18.0.1.0.0',
    'category': 'Examensbyrån/Death Services',
    'summary': 'Begravningsförsäkringsrådgivning för Examensbyrån',
    'description': '''
        Odoo-modul för att kartlägga begravningsförsäkringsbehov.

        Funktioner:
        - Jämförelsedatabas över svenska försäkringsaktörer
        - Självskattningsverktyg för användare
        - Kostnadskalkylator för begravningar
        - Personliga rekommendationer

        Del av Examensbyråns innehållsstrategi (fas 1).
    ''',
    'author': 'Arvas International AB',
    'website': 'https://examensbyran.se',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/providers_data.xml',
        'data/cost_components_data.xml',
        'views/examensbyran_insurance_provider_views.xml',
        'views/examensbyran_insurance_product_views.xml',
        'views/examensbyran_funeral_cost_component_views.xml',
        'views/examensbyran_funeral_assessment_views.xml',
        'views/menu.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
