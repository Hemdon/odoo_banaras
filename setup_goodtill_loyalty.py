#!/usr/bin/env python3
"""
Goodtill-style loyalty: custom loyalty categories (with parent groups) + product attach.

JSON schema (goodtill_loyalty.json v2):
  groups[]        → top level (paan, bubble_tea)
  categories[]    → redeem buckets (standard_paan, premium_paan, …) with products + optional match
  programs[]      → Rayners vs Hatch End with different point costs per category

Odoo: each category → product.tag GT-Loyalty:{key}; each program → loyalty.program on POS.

Run: sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d Main_Banaras --no-http \\
       < setup_goodtill_loyalty.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LOYALTY_JSON = Path("/opt/odoo/custom/goodtill_loyalty.json")
if not LOYALTY_JSON.exists():
    LOYALTY_JSON = Path(__file__).resolve().parent / "goodtill_loyalty.json"

COMPANY_ID = 4
GT_REF_PREFIX = "GT:"
LOYALTY_TAG_PREFIX = "GT-Loyalty:"
PROGRAM_REF_PREFIX = "GT-LOYALTY:"

POS_BY_NAME = {
    "Main Register": 9,
    "Hatch End Register": 13,
}


def load_config() -> dict:
    if not LOYALTY_JSON.exists():
        raise SystemExit("Missing goodtill_loyalty.json")
    return json.loads(LOYALTY_JSON.read_text())


def install_modules(env) -> None:
    to_install = env["ir.module.module"].search(
        [("name", "in", ["loyalty", "pos_loyalty"]), ("state", "!=", "installed")]
    )
    if to_install:
        to_install.button_immediate_install()
        env.cr.commit()
        env.registry.clear_cache()


def _template_for_500ml_variant(PT, base_name: str):
    base = (base_name or "").strip()
    if not base:
        return PT.browse()
    t = PT.search([("name", "=", base)], limit=1) or PT.search([("name", "ilike", base)], limit=1)
    if not t:
        return PT.browse()
    for v in t.product_variant_ids:
        size_vals = v.product_template_attribute_value_ids.mapped("name")
        if any("500" in (s or "").lower() for s in size_vals):
            return t
    if "500ml" in (t.name or "").lower():
        return t
    return PT.browse()


def find_templates(env, *, goodtill_ids: list, skus: list, names: list) -> list:
    PT = env["product.template"]
    found = PT.browse()
    if goodtill_ids:
        refs = [f"{GT_REF_PREFIX}{gid}" for gid in goodtill_ids]
        found |= PT.search([("default_code", "in", refs)])
    if skus:
        found |= PT.search([("default_code", "in", skus)])
    for name in names:
        needle = (name or "").strip()
        if not needle:
            continue
        t = PT.browse()
        if "(500ml)" in needle:
            t = _template_for_500ml_variant(PT, needle.replace("(500ml)", "").strip())
        if not t:
            t = PT.search([("name", "=", needle)], limit=1)
        if not t:
            t = PT.search([("name", "ilike", needle)], limit=1)
        if t:
            found |= t
    return found


def _ensure_pos_ready(templates) -> None:
    """Loyalty rewards must be POS products (template or at least one variant)."""
    for t in templates:
        if t.available_in_pos:
            continue
        if any(v.available_in_pos for v in t.product_variant_ids):
            continue
        t.write({"available_in_pos": True})
        if len(t.product_variant_ids) == 1:
            t.product_variant_ids.write({"available_in_pos": True})


def _text_matches(text: str, rules: dict) -> bool:
    n = (text or "").lower()
    all_req = [s.lower() for s in rules.get("name_contains_all") or []]
    any_req = [s.lower() for s in rules.get("name_contains_any") or []]
    excludes = [s.lower() for s in rules.get("name_excludes") or []]
    if all_req and not all(x in n for x in all_req):
        return False
    if any_req and not any(x in n for x in any_req):
        return False
    if excludes and any(x in n for x in excludes):
        return False
    return True


def match_templates(env, rules: dict) -> list:
    if not rules:
        return env["product.template"].browse()
    PT = env["product.template"]
    out = PT.browse()
    for t in PT.search([("available_in_pos", "=", True)]):
        if _text_matches(t.name, rules):
            out |= t
    # Bubble tea etc.: match variant display names (500ml / 700ml on attribute)
    PP = env["product.product"]
    for v in PP.search([("available_in_pos", "=", True)]):
        label = v.display_name or v.name
        if _text_matches(label, rules):
            out |= v.product_tmpl_id
    return out


def sync_category_products(env, category: dict) -> tuple:
    """Return (product.tag, template count)."""
    key = category["key"]
    tag_name = f"{LOYALTY_TAG_PREFIX}{key}"
    Tag = env["product.tag"]
    tag = Tag.search([("name", "=", tag_name)], limit=1) or Tag.create({"name": tag_name})

    products = category.get("products") or {}
    templates = find_templates(
        env,
        goodtill_ids=products.get("goodtill_ids") or [],
        skus=products.get("skus") or [],
        names=products.get("names") or [],
    )
    extra = category.get("match")
    if extra and (not templates or category.get("match_with_explicit")):
        templates |= match_templates(env, extra)
    _ensure_pos_ready(templates)
    templates = templates.filtered(
        lambda t: t.available_in_pos
        or any(v.available_in_pos for v in t.product_variant_ids)
    )

    PT = env["product.template"]
    tagged = PT.search([("product_tag_ids", "in", tag.id)])
    (tagged - templates).write({"product_tag_ids": [(3, tag.id)]})
    if templates:
        templates.write({"product_tag_ids": [(4, tag.id)]})
    return tag, len(templates)


def build_program(env, prog_cfg: dict, categories: dict, points_per: float) -> None:
    Program = env["loyalty.program"]
    ref = f"{PROGRAM_REF_PREFIX}{prog_cfg['key']}"
    pos_names = prog_cfg.get("pos_registers") or []
    pos_ids = [POS_BY_NAME[n] for n in pos_names if n in POS_BY_NAME]

    program = Program.search([("name", "=", ref)], limit=1)
    if not program:
        program = Program.search([("name", "=", prog_cfg["name"])], limit=1)
    if not program:
        program = Program.create(
            {
                "name": prog_cfg["name"],
                "program_type": "loyalty",
                "company_id": COMPANY_ID,
            }
        )

    reward_cmds = [(5, 0, 0)]
    for rw in prog_cfg.get("rewards") or []:
        cat_key = rw.get("category")
        cat = categories.get(cat_key)
        if not cat:
            print(f"  skip {rw.get('description')}: unknown category {cat_key}")
            continue
        tag, n = cat["tag"], cat["count"]
        if n == 0:
            print(f"  skip {rw.get('description')}: category {cat_key} has no products")
            continue
        pts = float(rw.get("points") or 0)
        reward_cmds.append(
            (
                0,
                0,
                {
                    "description": (rw.get("description") or cat_key)[:80],
                    "reward_type": "product",
                    "reward_product_tag_id": tag.id,
                    "reward_product_id": False,
                    "reward_product_qty": 1,
                    "required_points": pts,
                },
            )
        )
        parent = cat.get("parent", "")
        print(
            f"  {int(pts):3d} pts  {rw.get('description')[:42]:42}  "
            f"[{parent}/{cat_key}] {n} products"
        )

    if len(reward_cmds) <= 1:
        print(f"  WARNING: no rewards for program {prog_cfg['name']}")
        return

    program.write(
        {
            "name": prog_cfg["name"],
            "program_type": "loyalty",
            "company_id": COMPANY_ID,
            "trigger": "auto",
            "applies_on": "both",
            "is_nominative": True,
            "portal_visible": True,
            "portal_point_name": "Points",
            "active": True,
            "pos_config_ids": [(6, 0, pos_ids)],
            "rule_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "reward_point_mode": "money",
                        "reward_point_amount": points_per,
                        "minimum_qty": 0,
                        "minimum_amount": 0,
                        "mode": "auto",
                    },
                ),
            ],
            "reward_ids": reward_cmds,
        }
    )


def run(env) -> None:
    install_modules(env)
    cfg = load_config()
    points_per = float(cfg.get("points_per_currency") or 5)

    # Deactivate old single-program setup if present
    old = env["loyalty.program"].search(
        [("name", "in", ["Banaras Paan Loyalty", "GT-LOYALTY:BANARAS"])]
    )
    for p in old:
        if p.program_type == "loyalty" and not any(
            x.get("key", "").startswith("loyalty_") for x in cfg.get("programs", [])
        ):
            pass
    # deactivate demo
    env["loyalty.program"].browse(6).write({"active": False, "pos_config_ids": [(5, 0, 0)]})

    print("Loyalty categories (custom tags, not product.category):")
    categories: dict = {}
    for cat in cfg.get("categories") or []:
        tag, count = sync_category_products(env, cat)
        parent = cat.get("parent") or ""
        categories[cat["key"]] = {
            "tag": tag,
            "count": count,
            "parent": parent,
            "name": cat.get("name"),
        }
        group_label = f"{parent} → " if parent else ""
        print(f"  {group_label}{cat['key']}: {count} products  (tag {tag.name})")

    print("\nLoyalty programs:")
    for prog in cfg.get("programs") or []:
        print(f"\n{prog['name']}:")
        build_program(env, prog, categories, points_per)

    env.cr.commit()
    print("\nDone. Edit goodtill_loyalty.json → categories[].products to attach SKUs/Goodtill IDs.")
    print("Re-run this script after updating product lists. Close/reopen POS sessions.")


if "env" in dir():
    run(env)
