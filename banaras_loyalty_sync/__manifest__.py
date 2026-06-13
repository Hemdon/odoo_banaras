{
    "name": "Banaras Loyalty Balance Sync",
    "version": "2.0.0",
    "author": "Banaras Paan",
    "category": "Point of Sale",
    "summary": "Sync Banaras branch loyalty balances and auto-enroll customers across all branches",
    "depends": ["pos_loyalty", "hr"],
    "data": [
        "views/loyalty_program_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "banaras_loyalty_sync/static/src/js/manual_loyalty_redemption.js",
        ],
    },
    "post_init_hook": "post_init_flag_branch_programs",
    "installable": True,
    "license": "LGPL-3",
}
