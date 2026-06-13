{
    "name": "Banaras Paan Website",
    "version": "19.0.1.0.0",
    "category": "Theme/Food & Restaurant",
    "summary": "SEO-focused Banaras Paan storefront for Odoo eCommerce",
    "description": """
Banaras Paan branded website and eCommerce theme.

The module provides:
- A Paan-focused landing page
- Logo-matched indigo, blue, and green styling
- Responsive eCommerce product cards and product pages
- Public Paan category structure synchronized from POS categories
""",
    "author": "Banaras Paan",
    "license": "LGPL-3",
    "depends": [
        "website_sale",
        "website_sale_stock",
        "delivery",
    ],
    "data": [
        "data/product_public_categories.xml",
        "views/homepage.xml",
        "views/website_sale_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "theme_banaras_paan/static/src/scss/banaras_theme.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}

