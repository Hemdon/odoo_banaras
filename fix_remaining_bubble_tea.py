#!/usr/bin/env python3
"""Fix bubble teas on POS without Drink Size + hide leftover flat/copy cards."""

from __future__ import annotations

import re
from collections import defaultdict

ATTR_NAME = "Drink Size"
ML_END_RE = re.compile(r"(\d+)\s*ml\s*$", re.I)
ML_ANY_RE = re.compile(r"\d+\s*ml", re.I)
COPY_RE = re.compile(r"\(copy\)", re.I)


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def parse_size_line(name: str) -> tuple[str, str] | None:
    name = COPY_RE.sub("", name)
    name = normalize_spaces(name)
    m = ML_END_RE.search(name)
    if not m:
        return None
    size = f"{m.group(1)}ml"
    base = normalize_spaces(name[: m.start()])
    return base, size


def _copy_pricelist_from_flats(env, parent, items: list) -> None:
    PricelistItem = env["product.pricelist.item"]
    for pl_id in (1, 5):
        for it in items:
            flat, size, price = it["flat"], it["size"], it["price"]
            variant = parent.product_variant_ids.filtered(
                lambda v, s=size: s in (v.display_name or "").lower()
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
                [("pricelist_id", "=", pl_id), ("product_id", "=", variant.id)],
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
    size_attr = env["product.attribute"].search([("name", "=", ATTR_NAME)], limit=1)
    AttrVal = env["product.attribute.value"]
    cats = env["pos.category"].search([("name", "in", ["Bubble Fruit Tea", "Bubble Milk Tea"])])
    bubble = PT.search([("pos_categ_ids", "in", cats.ids)])
    combo_ids = env["product.combo"].search(
        [("name", "in", ["Popping Boba", "Pearls & Jelly"])]
    ).ids

    flats = bubble.filtered(
        lambda t: ML_ANY_RE.search(t.name or "")
        and not any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)
    )
    groups = defaultdict(list)
    for flat in flats:
        parsed = parse_size_line(flat.name)
        if not parsed:
            continue
        base, size = parsed
        groups[norm_key(base)].append(
            {"base": base, "size": size, "price": flat.list_price, "flat": flat}
        )

    fixed = 0
    for nk, items in groups.items():
        if len(items) < 2:
            continue
        parent = bubble.filtered(
            lambda t, k=nk: t.available_in_pos
            and not any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)
            and not ML_ANY_RE.search(t.name or "")
            and (norm_key(t.name) == k or k in norm_key(t.name))
        )[:1]
        if not parent:
            continue
        sizes = {it["size"]: it["price"] for it in items}
        min_size = min(sizes.keys(), key=lambda s: (int(re.sub(r"\D", "", s)), s))
        base_price = sizes[min_size]
        value_ids = []
        for size in sorted(sizes.keys(), key=lambda s: (int(re.sub(r"\D", "", s)), s)):
            extra = round(sizes[size] - base_price, 2)
            val = AttrVal.search(
                [("attribute_id", "=", size_attr.id), ("name", "=", size)], limit=1
            )
            if not val:
                val = AttrVal.create(
                    {"attribute_id": size_attr.id, "name": size, "default_extra_price": extra}
                )
            value_ids.append(val.id)
        parent.write(
            {
                "list_price": base_price,
                "combo_ids": [(6, 0, combo_ids)],
                "attribute_line_ids": [
                    (5, 0, 0),
                    (0, 0, {"attribute_id": size_attr.id, "value_ids": [(6, 0, value_ids)]}),
                ],
            }
        )
        parent._create_variant_ids()
        _copy_pricelist_from_flats(env, parent, items)
        for it in items:
            it["flat"].write({"available_in_pos": False})
        fixed += 1
        print(f"Fixed {parent.name}")

    left = bubble.filtered(
        lambda t: t.available_in_pos
        and (ML_ANY_RE.search(t.name or "") or COPY_RE.search(t.name or ""))
        and not any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)
    )
    left.write({"available_in_pos": False})
    env.cr.commit()
    on_pos = bubble.filtered(
        lambda t: t.available_in_pos
        and any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)
    )
    print(f"Fixed {fixed}; hid {len(left)} flats; {len(on_pos)} drinks with sizes on POS")


if "env" in dir():
    run(env)
