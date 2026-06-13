{
    "name": "Banaras POS Topping Labels",
    "version": "1.3.0",
    "category": "Point of Sale",
    "summary": "Short topping names on POS, full names on receipts",
    "depends": ["point_of_sale", "pos_self_order", "pos_restaurant"],
    "data": [],
    "assets": {
        "point_of_sale._assets_pos": [
            "banaras_pos_topping/static/src/js/pos_topping_names.js",
            "banaras_pos_topping/static/src/css/hide_tables_button.css",
            "banaras_pos_topping/static/src/xml/combo_configurator_popup.xml",
        ],
        "pos_self_order.assets": [
            "banaras_pos_topping/static/src/js/self_order_paan_groups.js",
            "banaras_pos_topping/static/src/js/self_order_uk_phone.js",
            "banaras_pos_topping/static/src/js/self_order_royal_offer.js",
            "banaras_pos_topping/static/src/xml/self_order_paan_groups.xml",
            "banaras_pos_topping/static/src/xml/self_order_uk_phone.xml",
        ],
    },
    "installable": True,
    "license": "LGPL-3",
}
