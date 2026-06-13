{
    "name": "Banaras Customer History",
    "version": "1.1.0",
    "category": "Contacts",
    "summary": "Store Good Till customer migration and purchase history metadata",
    "depends": ["contacts", "pos_loyalty"],
    "data": ["views/res_partner_views.xml"],
    "assets": {
        "point_of_sale._assets_pos": [
            "banaras_customer_history/static/src/xml/partner_loyalty_points.xml",
        ],
    },
    "installable": True,
    "license": "LGPL-3",
}
