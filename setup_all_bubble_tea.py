#!/usr/bin/env python3
"""
Convert all Bubble Fruit Tea + Bubble Milk Tea products to variant + combo format
(same as Banaras Lemon Fruit Tea POC) for both POS branches.

- Groups flat *ml products into one parent with Drink Size attribute
- Links shared Popping Boba / Pearls & Jelly combos (max 10 each)
- Short POS names + full receipt names on toppings
- Hides legacy flat size cards from POS

Run on server:
  sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d Main_Banaras --no-http < setup_all_bubble_tea.py
"""

from __future__ import annotations

import re
from collections import defaultdict

BUBBLE_POS_CATEGORIES = ("Bubble Fruit Tea", "Bubble Milk Tea")
ATTR_NAME = "Drink Size"
COMPANY_ID = 4
TAX_0_ID = 24
TOPPING_QTY_MAX = 10
TOPPING_CATEGORY = "Toppings"

ML_RE = re.compile(r"(\d+)\s*ml\s*$", re.I)
COPY_RE = re.compile(r"\s*\(copy\)\s*$", re.I)

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


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def pos_short_name(receipt_name: str) -> str:
    n = receipt_name.strip()
    for suffix in (" Popping", " Jelly"):
        if n.endswith(suffix):
            return n[: -len(suffix)]
    return n


def parse_size_line(name: str) -> tuple[str, str, float] | None:
    """Return (base_name, size_label e.g. 500ml, price) or None."""
    name = COPY_RE.sub("", name)
    name = normalize_spaces(name)
    m = ML_RE.search(name)
    if not m:
        return None
    size = f"{m.group(1)}ml"
    base = normalize_spaces(name[: m.start()])
    return base, size, 0.0


def _copy_pricelist_from_flats(env, parent, items: list) -> None:
    """Copy branch pricelist fixed prices from old flat templates to new size variants."""
    PricelistItem = env["product.pricelist.item"]
    for pl_id in (1, 5):  # Rayners Lane + Hatch End
        for it in items:
            flat = it["flat"]
            size = it["size"]
            price = it["price"]
            variant = parent.product_variant_ids.filtered(
                lambda v, s=size: s in (v.display_name or "")
            )[:1]
            if not variant:
                continue
            old_items = PricelistItem.search(
                [
                    ("pricelist_id", "=", pl_id),
                    "|",
                    ("product_tmpl_id", "=", flat.id),
                    ("product_id", "in", flat.product_variant_ids.ids),
                ]
            )
            target_price = price
            if old_items:
                fixed = [x.fixed_price for x in old_items if x.fixed_price]
                if fixed:
                    target_price = fixed[0]
            existing = PricelistItem.search(
                [
                    ("pricelist_id", "=", pl_id),
                    ("product_id", "=", variant.id),
                ],
                limit=1,
            )
            vals = {
                "pricelist_id": pl_id,
                "product_id": variant.id,
                "compute_price": "fixed",
                "fixed_price": target_price,
            }
            if existing:
                existing.write(vals)
            else:
                PricelistItem.create(vals)


def run(env) -> None:
    PT = env["product.template"]
    Attr = env["product.attribute"]
    AttrVal = env["product.attribute.value"]
    Combo = env["product.combo"]
    PosCat = env["pos.category"]

    bubble_cats = PosCat.search([("name", "in", list(BUBBLE_POS_CATEGORIES))])
    if len(bubble_cats) < 2:
        raise SystemExit(f"Missing POS categories: {BUBBLE_POS_CATEGORIES}")

    top_cat = PosCat.search([("name", "=", TOPPING_CATEGORY)], limit=1)
    if not top_cat:
        top_cat = PosCat.create({"name": TOPPING_CATEGORY})

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

    def ensure_topping(receipt_name: str, price: float):
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

    def ensure_combo(name: str, toppings: list[tuple[str, float]]):
        variant_ids = [ensure_topping(n, p).id for n, p in toppings]
        combo = Combo.search([("name", "=", name)], limit=1)
        item_cmds = [(5, 0, 0)] + [
            (0, 0, {"product_id": vid, "extra_price": 0.0}) for vid in variant_ids
        ]
        vals = {
            "name": name,
            "company_id": COMPANY_ID,
            "qty_max": TOPPING_QTY_MAX,
            "qty_free": 0,
            "combo_item_ids": item_cmds,
        }
        if combo:
            combo.write(vals)
        else:
            combo = Combo.create(vals)
        return combo

    combo_popping = ensure_combo("Popping Boba", POPPING_BOBA)
    combo_pearls = ensure_combo("Pearls & Jelly", PEARLS_JELLY)
    combo_ids = [combo_popping.id, combo_pearls.id]

    # All bubble templates (including hidden flats)
    domain = [("pos_categ_ids", "in", bubble_cats.ids)]
    all_bubble = PT.search(domain)

    # Already configured parents
    configured = all_bubble.filtered(
        lambda t: any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)
        and t.combo_ids
    )

    # Flat size lines still on POS
    flats = all_bubble.filtered(
        lambda t: t.available_in_pos
        and ML_RE.search(t.name or "")
        and not any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)
    )

    # Group flats by normalized base name
    groups: dict[str, list] = defaultdict(list)
    for flat in flats:
        parsed = parse_size_line(flat.name)
        if not parsed:
            continue
        base, size, _ = parsed
        price = flat.list_price
        pos_cat = flat.pos_categ_ids[:1]
        groups[norm_key(base)].append(
            {
                "base": base,
                "size": size,
                "price": price,
                "flat": flat,
                "pos_cat_id": pos_cat.id if pos_cat else bubble_cats[0].id,
            }
        )

    # Parents without ml already on POS (single card — may need combos only)
    group_keys = set(groups.keys())
    standalone = all_bubble.filtered(
        lambda t: t.available_in_pos
        and not ML_RE.search(t.name or "")
        and not COPY_RE.search(t.name or "")
        and not any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)
        and norm_key(t.name) not in group_keys
    )

    def find_parent_template(base: str, pos_cat_id: int):
        nk = norm_key(base)
        # Exact / normalized match among bubble products without ml
        for t in all_bubble:
            if ML_RE.search(t.name or ""):
                continue
            if norm_key(t.name) == nk:
                return t
        # Parent name sometimes adds "Tea"
        for t in all_bubble:
            if ML_RE.search(t.name or ""):
                continue
            tn = norm_key(t.name)
            if nk in tn or tn in nk:
                return t
        # Create new parent
        display = base if "tea" in base.lower() else f"{base} Tea"
        return PT.create(
            {
                "name": normalize_spaces(display),
                "list_price": 0,
                "type": "consu",
                "available_in_pos": True,
                "sale_ok": True,
                "company_id": COMPANY_ID,
                "pos_categ_ids": [(6, 0, [pos_cat_id])],
                "taxes_id": [(6, 0, [TAX_0_ID])],
            }
        )

    converted = skipped = errors = 0
    flat_hidden = 0

    for _nk, items in sorted(groups.items(), key=lambda x: x[1][0]["base"]):
        items.sort(key=lambda x: (len(x["size"]), x["size"]))
        base = items[0]["base"]
        pos_cat_id = items[0]["pos_cat_id"]
        try:
            parent = find_parent_template(base, pos_cat_id)
            sizes = {it["size"]: it["price"] for it in items}
            min_size = min(sizes.keys(), key=lambda s: (int(re.sub(r"\D", "", s)), s))
            base_price = sizes[min_size]

            value_cmds = []
            for size in sorted(sizes.keys(), key=lambda s: (int(re.sub(r"\D", "", s)), s)):
                extra = round(sizes[size] - base_price, 2)
                value_cmds.append(attr_value(size, extra).id)

            parent.write(
                {
                    "list_price": base_price,
                    "available_in_pos": True,
                    "sale_ok": True,
                    "type": "consu",
                    "pos_categ_ids": [(6, 0, [pos_cat_id])],
                    "taxes_id": [(6, 0, [TAX_0_ID])],
                    "combo_ids": [(6, 0, combo_ids)],
                    "attribute_line_ids": [
                        (5, 0, 0),
                        (
                            0,
                            0,
                            {
                                "attribute_id": size_attr.id,
                                "value_ids": [(6, 0, value_cmds)],
                            },
                        ),
                    ],
                }
            )
            parent._create_variant_ids()
            _copy_pricelist_from_flats(env, parent, items)
            for it in items:
                it["flat"].write({"available_in_pos": False})
                flat_hidden += 1
            converted += 1
            sizes_str = ", ".join(f"{s} £{sizes[s]:.2f}" for s in sorted(sizes))
            print(f"OK  {parent.name}  [{sizes_str}]")
        except Exception as e:
            errors += 1
            print(f"ERR {base}: {e}")

    # Standalone bubble drinks (no size variants in Odoo) — attach combos only
    for tmpl in standalone:
        if tmpl in configured:
            skipped += 1
            continue
        try:
            tmpl.write(
                {
                    "combo_ids": [(6, 0, combo_ids)],
                    "available_in_pos": True,
                    "taxes_id": [(6, 0, [TAX_0_ID])],
                }
            )
            converted += 1
            print(f"OK  {tmpl.name}  (combos only, no sizes)")
        except Exception as e:
            errors += 1
            print(f"ERR {tmpl.name}: {e}")

    # Ensure POC parent still correct
    for t in configured:
        if not t.combo_ids:
            t.write({"combo_ids": [(6, 0, combo_ids)]})

    env.cr.commit()
    print(
        f"\nDone: {converted} configured, {flat_hidden} flat size cards hidden, "
        f"{len(configured)} already had variants, {errors} errors"
    )
    print("Close all POS sessions on Main Register + Hatch End and reopen.")


if "env" in dir():
    run(env)
