#!/usr/bin/env python3
"""Hide leftover flat/copy bubble tea cards after setup_all_bubble_tea.py."""

from __future__ import annotations

import re

ML_RE = re.compile(r"\d+\s*ml", re.I)
COPY_RE = re.compile(r"\(copy\)", re.I)


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def run(env) -> None:
    PT = env["product.template"]
    cats = env["pos.category"].search([("name", "in", ["Bubble Fruit Tea", "Bubble Milk Tea"])])
    bubble = PT.search([("pos_categ_ids", "in", cats.ids)])
    size_attr = env["product.attribute"].search([("name", "=", "Drink Size")], limit=1)

    def has_size_attr(t):
        return any(l.attribute_id.id == size_attr.id for l in t.attribute_line_ids)

    to_hide = bubble.filtered(
        lambda t: t.available_in_pos
        and (ML_RE.search(t.name or "") or COPY_RE.search(t.name or ""))
        and not has_size_attr(t)
    )
    to_hide.write({"available_in_pos": False})

    with_variants = bubble.filtered(has_size_attr)
    variant_keys = {norm_key(t.name) for t in with_variants}
    dup_parents = bubble.filtered(
        lambda t: t.available_in_pos
        and not has_size_attr(t)
        and not ML_RE.search(t.name or "")
        and norm_key(t.name) in variant_keys
    )
    dup_parents.write({"available_in_pos": False})

    combo_ids = env["product.combo"].search(
        [("name", "in", ["Popping Boba", "Pearls & Jelly"])]
    ).ids
    for t in with_variants:
        if set(t.combo_ids.ids) != set(combo_ids):
            t.write({"combo_ids": [(6, 0, combo_ids)]})

    env.cr.commit()
    on_pos = with_variants.filtered(lambda t: t.available_in_pos)
    print(f"Hidden flats/copies: {len(to_hide)}")
    print(f"Hidden duplicate parents: {len(dup_parents)}")
    print(f"Bubble drinks on POS (with sizes): {len(on_pos)}")


if "env" in dir():
    run(env)
