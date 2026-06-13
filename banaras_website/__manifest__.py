{
    'name': 'Banaras Paan Website',
    'version': '19.0.1.0.0',
    'category': 'Website',
    'summary': 'Banaras Paan home page, branding and SEO (migrated from WordPress)',
    'description': "Banaras Paan website pages (Home, About Us) migrated from "
                   "WordPress: branded responsive layout, brand palette from the "
                   "logo, and on-page SEO with JSON-LD structured data.",
    'author': 'Banaras Paan',
    'website': 'https://www.banaraspaan.com',
    'depends': ['website'],
    'data': [
        'views/homepage.xml',
        'views/about.xml',
        'views/uk_wide_orders.xml',
        'views/local_orders.xml',
        'views/event_party.xml',
        'views/franchise.xml',
        'views/apply_to_partner.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'banaras_website/static/src/css/banaras.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
