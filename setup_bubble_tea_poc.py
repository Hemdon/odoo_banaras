#!/usr/bin/env python3
"""
POC: Banaras Lemon Fruit Tea with Odoo POS variants + combo choices (Goodtill-style).

- Size attribute: 500ml / 700ml (prices from Goodtill)
- Combo groups: Popping Boba, Pearls & Jelly (max 10 each; short POS name, full receipt via banaras_pos_topping)
- Hides the old flat 500ml / 700ml product cards from POS

Run on server:
  sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d Main_Banaras --no-http < setup_bubble_tea_poc.py

Requires POS patch so combo toppings load for type=consu products (not only type=combo).
See docs/POS_COMBO_PATCH.md — applied on 187.77.99.211 May 2026.

Or: python3 setup_bubble_tea_poc.py  (uses ODOO_URL from .env via xmlrpc — optional)
"""

from __future__ import annotations

# --- Goodtill reference (Main outlet) ---
PARENT_NAME = "Banaras Lemon Fruit Tea"
FLAT_500_NAMES = ("Banaras Lemon  Fruit Tea 500ml", "Banaras Lemon Fruit Tea 500ml")
FLAT_700_NAMES = ("Banaras Lemon Fruit  Tea 700ml", "Banaras Lemon Fruit Tea 700ml")
PRICE_500 = 4.24
PRICE_700 = 4.69
POS_CATEGORY = "Bubble Fruit Tea"
ATTR_NAME = "Drink Size"
COMPANY_ID = 4
TAX_0_ID = 24  # 0% NO VAT on Banaras Paan
TOPPING_QTY_MAX = 10


def pos_short_name(receipt_name: str) -> str:
    n = receipt_name.strip()
    for suffix in (" Popping", " Jelly"):
        if n.endswith(suffix):
            return n[: -len(suffix)]
    return n

POPPING_BOBA = [
    ("Apple Popping", 0.45),
    ("Blueberry Popping", 0.45),
    ("Cherry Popping", 0.45),
    ("Lychee Popping", 0.45),
    ("Mango Popping", 0.45),
    ("Passion Popping", 0.45),
    ("Peach Popping", 0.45),
    ("Raspberry Popping", 0.45),
    ("Strawberry Popping", 0.45),
    ("Chocolate Popping", 0.45),
    ("Pineapple Popping", 0.45),
    ("Kiwi Fruit Popping", 0.45),
    ("Lemon Popping", 0.45),
    ("HoneyDew Popping", 0.45),
]

PEARLS_JELLY = [
    ("Topioca Pearl", 0.45),
    ("Mango Jelly", 0.49),
    ("Coconut Jelly", 0.45),
    ("Lychee Coconut Jelly", 0.45),
    ("PINEAPPLE Jelly", 0.49),
    ("STRAWBERRY Jelly", 0.49),
]


def run(env) -> None:
    PT = env["product.template"]
    PP = env["product.product"]
    Attr = env["product.attribute"]
    AttrVal = env["product.attribute.value"]
    Combo = env["product.combo"]
    PosCat = env["pos.category"]

    parent = PT.search([("name", "=", PARENT_NAME)], limit=1)
    if not parent:
        raise SystemExit(f"Product not found: {PARENT_NAME}")

    pos_cat = PosCat.search([("name", "=", POS_CATEGORY)], limit=1)
    if not pos_cat:
        raise SystemExit(f"POS category not found: {POS_CATEGORY}")

    top_cat = PosCat.search([("name", "=", "Toppings")], limit=1)
    if not top_cat:
        top_cat = PosCat.create({"name": "Toppings"})
        print(f"Created POS category Toppings (id={top_cat.id}) — not added to registers")

    # Hide legacy flat size products from POS
    flat_names = list(dict.fromkeys(FLAT_500_NAMES + FLAT_700_NAMES))
    flats = PT.search([("name", "in", flat_names)]) if flat_names else PT.browse()
    if flats:
        flats.write({"available_in_pos": False})
        print(f"Removed {len(flats)} flat size product(s) from POS: {flats.mapped('name')}")

    # Drink Size attribute
    size_attr = Attr.search([("name", "=", ATTR_NAME)], limit=1)
    if not size_attr:
        size_attr = Attr.create({"name": ATTR_NAME, "create_variant": "always"})

    def attr_value(name: str, extra: float = 0.0):
        val = AttrVal.search(
            [("attribute_id", "=", size_attr.id), ("name", "=", name)], limit=1
        )
        if not val:
            val = AttrVal.create(
                {"attribute_id": size_attr.id, "name": name, "default_extra_price": extra}
            )
        elif val.default_extra_price != extra:
            val.default_extra_price = extra
        return val

    v500 = attr_value("500ml", 0.0)
    v700 = attr_value("700ml", round(PRICE_700 - PRICE_500, 2))

    parent.write(
        {
            "list_price": PRICE_500,
            "available_in_pos": True,
            "sale_ok": True,
            "type": "consu",
            "pos_categ_ids": [(6, 0, [pos_cat.id])],
            "taxes_id": [(6, 0, [TAX_0_ID])],
            "attribute_line_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "attribute_id": size_attr.id,
                        "value_ids": [(6, 0, [v500.id, v700.id])],
                    },
                ),
            ],
        }
    )
    parent._create_variant_ids()
    print(f"Parent {parent.name}: {len(parent.product_variant_ids)} variant(s)")
    for v in parent.product_variant_ids:
        print(f"  - {v.display_name}  £{v.lst_price:.2f}")

    def ensure_topping(receipt_name: str, price: float) -> PP:
        code = "TOP:" + receipt_name.upper().replace(" ", "_")[:40]
        tmpl = PT.search([("default_code", "=", code)], limit=1)
        vals = {
            "name": pos_short_name(receipt_name),
            "description_sale": receipt_name,
            "list_price": price,
            "default_code": code,
            "type": "consu",
            "available_in_pos": True,
            "sale_ok": True,
            "company_id": COMPANY_ID,
            "pos_categ_ids": [(6, 0, [top_cat.id])],
            "taxes_id": [(6, 0, [TAX_0_ID])],
        }
        if tmpl:
            tmpl.write(vals)
        else:
            tmpl = PT.create(vals)
        return tmpl.product_variant_ids[0]

    def ensure_combo(name: str, qty_max: int, toppings: list[tuple[str, float]]) -> Combo:
        variant_ids = [ensure_topping(n, p).id for n, p in toppings]
        combo = Combo.search([("name", "=", name)], limit=1)
        item_cmds = [(5, 0, 0)]
        item_cmds += [
            (0, 0, {"product_id": vid, "extra_price": 0.0}) for vid in variant_ids
        ]
        combo_vals = {
            "name": name,
            "company_id": COMPANY_ID,
            "qty_max": qty_max,
            "qty_free": 0,
            "combo_item_ids": item_cmds,
        }
        if combo:
            combo.write(combo_vals)
        else:
            combo = Combo.create(combo_vals)
        print(f"Combo '{name}': {len(variant_ids)} choices, max {qty_max}")
        return combo

    combo_popping = ensure_combo("Popping Boba", TOPPING_QTY_MAX, POPPING_BOBA)
    combo_pearls = ensure_combo("Pearls & Jelly", TOPPING_QTY_MAX, PEARLS_JELLY)

    parent.write({"combo_ids": [(6, 0, [combo_popping.id, combo_pearls.id])]})
    print(f"Linked combos to {parent.name}: {parent.combo_ids.mapped('name')}")

    env.cr.commit()
    print("\nPOC ready. Close/reopen POS session, then open:")
    print("  Bubble Fruit Tea → Banaras Lemon Fruit Tea")
    print(f"  1) Pick 500ml or 700ml  2) Add up to {TOPPING_QTY_MAX} toppings per group")


# Odoo shell execution
if "env" in dir():
    run(env)
