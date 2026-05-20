#!/usr/bin/env python3
"""Run on server: sudo -u odoo odoo shell -d Main_Banaras -c /etc/odoo/odoo.conf --no-http < fix_chart_rayner.py"""
import logging
logging.getLogger("odoo").setLevel(logging.ERROR)

Chart = env["account.chart.template"]
paan = env["res.company"].search([("name", "=", "Banaras Paan")], limit=1)
rayner = env["res.company"].search([("name", "=", "Banaras - RaynerLane")], limit=1)
uk = env.ref("base.uk")
london = env.ref("base.state_uk119")

paan.partner_id.write({"country_id": uk.id, "state_id": london.id})
Chart.try_loading("uk", paan, install_demo=False, force_create=True)

accounts = env["account.account"].with_company(paan).search([("code", "=like", "1210%")], limit=1)
if not accounts:
    accounts = env["account.account"].with_company(paan).search([("account_type", "=", "asset_cash")], limit=1)

cash_j = env["account.journal"].search([("company_id", "=", paan.id), ("type", "=", "cash")], limit=1)
if not cash_j and accounts:
    cash_j = env["account.journal"].create({
        "name": "Cash",
        "code": "CSH1",
        "type": "cash",
        "company_id": paan.id,
        "default_account_id": accounts[0].id,
    })
    print("Created cash journal on Banaras Paan")

sale_j = env["account.journal"].search([("company_id", "=", paan.id), ("type", "=", "sale")], limit=1)
bank_j = env["account.journal"].search([("company_id", "=", paan.id), ("type", "=", "bank")], limit=1)

if not rayner.chart_template:
    rayner.chart_template = "uk"

gbp = env.ref("base.GBP")
wh = env["stock.warehouse"].search([("company_id", "=", rayner.id)], limit=1)
if not wh:
    wh = env["stock.warehouse"].create({"name": "Rayners Lane", "code": "RL", "company_id": rayner.id})

pl = env["product.pricelist"].search([("company_id", "=", rayner.id)], limit=1)
if not pl:
    pl = env["product.pricelist"].create({"name": "Rayners Lane (GBP)", "currency_id": gbp.id, "company_id": rayner.id})

cats = env["pos.category"].search([
    ("name", "in", [
        "Paan", "Bubble Tea", "Freeze Drinks", "Paan Masala", "Paan Mukhwas",
        "Sweets and Candy", "Mocktails", "MISC", "Indian Stuffs", "Thick Milk Shake",
        "Banaras Hot Drinks", "Falooda", "Drinks", "ICE Gola", "Hot Drinks",
        "TBC", "Chakhna", "Thandai",
    ])
])

pos = env["pos.config"].search([("company_id", "=", rayner.id)], limit=1)
if not pos:
    cash_pm = env["pos.payment.method"].create({"name": "Cash", "journal_id": cash_j.id, "company_id": rayner.id})
    card_pm = env["pos.payment.method"].create({"name": "Card", "journal_id": bank_j.id, "company_id": rayner.id})
    pos = env["pos.config"].create({
        "name": "Main Register",
        "company_id": rayner.id,
        "warehouse_id": wh.id,
        "journal_id": cash_j.id,
        "invoice_journal_id": sale_j.id,
        "pricelist_id": pl.id,
        "currency_id": gbp.id,
        "payment_method_ids": [(6, 0, [cash_pm.id, card_pm.id])],
        "limit_categories": True,
        "iface_available_categ_ids": [(6, 0, cats.ids)],
        "iface_group_by_categ": True,
        "show_product_images": True,
        "show_category_images": True,
    })
    print("Created POS id", pos.id)
else:
    pos.write({
        "journal_id": cash_j.id,
        "invoice_journal_id": sale_j.id,
        "limit_categories": True,
        "iface_available_categ_ids": [(6, 0, cats.ids)],
    })
    for pm in env["pos.payment.method"].search([("company_id", "=", rayner.id)]):
        if "cash" in (pm.name or "").lower():
            pm.journal_id = cash_j
        if "card" in (pm.name or "").lower():
            pm.journal_id = bank_j
    print("Updated POS id", pos.id)

pos._compute_company_has_template()
print("company_has_template:", pos.company_has_template)
print("cash:", cash_j.code, "sale:", sale_j.code)
env.cr.commit()
print("DONE config_id=", pos.id)
