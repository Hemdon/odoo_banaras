{
    "name": "Banaras POS Topping Labels",
    "version": "1.0.0",
    "category": "Point of Sale",
    "summary": "Short topping names on POS, full names on receipts",
    "depends": ["point_of_sale"],
    "data": [],
    "assets": {
        "point_of_sale._assets_pos": [
            "banaras_pos_topping/static/src/js/pos_topping_names.js",
            "banaras_pos_topping/static/src/xml/combo_configurator_popup.xml",
        ],
    },
    "installable": True,
    "license": "LGPL-3",
}
