#!/usr/bin/env python3
"""
Sync Goodtill promotions & coupons to Odoo loyalty (both POS branches).

- /api/external/promotions → buy_x_get_y (Buy N Get M FREE) & % promos per outlet tag
- Coupons + legacy HP/BOGOF → promo_code
- BNRSUK → Main Register (9), BNRSHE → Hatch End Register (13)

Branch selling prices stay on pricelists (1 / 5); promos apply on top at each register.

Requires: loyalty + pos_loyalty. Run fetch_goodtill_promotions.py first.

Server:
  sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d Main_Banaras --no-http \\
    < setup_goodtill_promotions.py
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

FLAGS_JSON = Path(__file__).resolve().parent / "goodtill_promotions.json"
GT_PREFIX = "GT-PROMO:"
GT_REF_PREFIX = "GT:"
COMPANY_ID = 4
POS_MAIN = 9
POS_HATCH = 13

OUTLET_POS = {
    "Main Outlet": [POS_MAIN],
    "Banaras Paan - Hatch End": [POS_HATCH],
}

OUTLET_TAG_POS = {
    "BNRSUK": [POS_MAIN],   # Rayners Lane
    "BNRSHE": [POS_HATCH],  # Hatch End
}

BUY_GET_FREE = re.compile(r"Buy\s+(\d+)\s+Get\s+(\d+)\s+FREE", re.IGNORECASE)

OUTLET_SUFFIX = {
    "BNRSUK": " (Rayners)",
    "BNRSHE": " (Hatch End)",
}


def load_data() -> dict:
    if not FLAGS_JSON.exists():
        raise SystemExit("Run fetch_goodtill_promotions.py first.")
    return json.loads(FLAGS_JSON.read_text())


def install_loyalty_modules(env) -> None:
    to_install = env["ir.module.module"].search(
        [("name", "in", ["loyalty", "pos_loyalty"]), ("state", "!=", "installed")]
    )
    if to_install:
        print("Installing modules:", to_install.mapped("name"))
        to_install.button_immediate_install()
        env.cr.commit()
        env.registry.clear_cache()


def pos_ids_for_coupon(coupon: dict) -> list[int]:
    outlet = (coupon.get("outlet_name") or "").strip()
    if outlet in OUTLET_POS:
        return OUTLET_POS[outlet]
    if coupon.get("is_outlet_restricted"):
        return []
    return [POS_MAIN, POS_HATCH]


def pos_ids_for_promo(promo: dict) -> list[int]:
    tags = promo.get("outlet_tags") or []
    if not tags:
        return [POS_MAIN, POS_HATCH]
    pos: list[int] = []
    for tag in tags:
        pos.extend(OUTLET_TAG_POS.get(tag, []))
    return list(dict.fromkeys(pos))


def bubble_tea_variant_ids(env) -> list[int]:
    cats = env["pos.category"].search([("name", "ilike", "Bubble")])
    tmpls = env["product.template"].search(
        [("available_in_pos", "=", True), ("pos_categ_ids", "in", cats.ids)]
    )
    return tmpls.mapped("product_variant_ids").ids


def resolve_variant_ids(env, promo: dict) -> list[int]:
    PT = env["product.template"]
    variant_ids: list[int] = []
    for gp in promo.get("products") or []:
        sku = (gp.get("product_sku") or "").strip()
        gid = (gp.get("product_id") or "").strip()
        tmpl = PT.browse()
        if sku:
            tmpl = PT.search([("default_code", "=", sku)], limit=1)
        if not tmpl and gid:
            tmpl = PT.search([("default_code", "=", f"{GT_REF_PREFIX}{gid}")], limit=1)
        if not tmpl and gp.get("product_name"):
            tmpl = PT.search([("name", "=", gp["product_name"])], limit=1)
        if tmpl and tmpl.available_in_pos:
            variant_ids.append(tmpl.product_variant_ids[0].id)
    variant_ids = list(dict.fromkeys(variant_ids))
    title = (promo.get("promo_name") or "").lower()
    if "bubble tea" in title and len(variant_ids) < 5:
        variant_ids = bubble_tea_variant_ids(env)
    return variant_ids


def program_ref(gt_id: str) -> str:
    """Stable id used to find programs created before display-name sync."""
    return f"{GT_PREFIX}{gt_id}"


def display_name_from_promo(promo: dict) -> str:
    title = (promo.get("promo_name") or promo.get("description") or "Promotion").strip()
    tags = promo.get("outlet_tags") or []
    if len(tags) == 1 and tags[0] in OUTLET_SUFFIX:
        title += OUTLET_SUFFIX[tags[0]]
    return title[:128]


def find_program(env, gt_id: str, display_name: str):
    Program = env["loyalty.program"]
    for name in (program_ref(gt_id), display_name):
        program = Program.search([("name", "=", name)], limit=1)
        if program:
            return program
    return Program.browse()


def create_promo_code_program(
    env,
    *,
    name: str,
    code: str,
    discount: float,
    is_percent: bool,
    date_to: str | None,
    date_from: str | None,
    pos_ids: list[int],
    max_uses: int = 0,
) -> None:
    Program = env["loyalty.program"]
    display_name = name.strip() or code
    program = find_program(env, code, display_name) or Program.create(
        {"name": display_name, "program_type": "promo_code", "company_id": COMPANY_ID}
    )

    rule_vals = {
        "mode": "with_code",
        "code": code.upper(),
        "minimum_qty": 0,
        "minimum_amount": 0,
    }
    reward_vals = {
        "reward_type": "discount",
        "discount_applicability": "order",
        "required_points": 1,
        "description": name[:80],
    }
    if is_percent:
        reward_vals.update({"discount_mode": "percent", "discount": discount})
    else:
        reward_vals.update({"discount_mode": "per_order", "discount": discount})

    program.write(
        {
            "name": display_name,
            "program_type": "promo_code",
            "company_id": COMPANY_ID,
            "trigger": "with_code",
            "active": True,
            "pos_config_ids": [(6, 0, pos_ids)],
            "date_from": date_from or False,
            "date_to": date_to or False,
            "limit_usage": bool(max_uses),
            "max_usage": max_uses if max_uses else 0,
            "rule_ids": [(5, 0, 0), (0, 0, rule_vals)],
            "reward_ids": [(5, 0, 0), (0, 0, reward_vals)],
        }
    )
    print(f"  code {code:16} → {display_name[:42]:42} POS {pos_ids}")


def create_buy_x_get_y(
    env,
    *,
    gt_id: str,
    title: str,
    buy_qty: int,
    free_qty: int,
    variant_ids: list[int],
    pos_ids: list[int],
    date_from: str | None,
    date_to: str | None,
) -> None:
    if not variant_ids or not pos_ids:
        return
    Program = env["loyalty.program"]
    display_name = title.strip()
    program = find_program(env, gt_id, display_name) or Program.create(
        {
            "name": display_name,
            "program_type": "buy_x_get_y",
            "company_id": COMPANY_ID,
        }
    )
    program.write(
        {
            "name": display_name,
            "program_type": "buy_x_get_y",
            "company_id": COMPANY_ID,
            "trigger": "auto",
            "applies_on": "current",
            "active": True,
            "pos_config_ids": [(6, 0, pos_ids)],
            "date_from": (date_from or "")[:10] or False,
            "date_to": (date_to or "")[:10] or False,
            "rule_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "product_ids": [(6, 0, variant_ids)],
                        "minimum_qty": buy_qty,
                        "reward_point_amount": 1,
                        "reward_point_mode": "unit",
                        "mode": "auto",
                    },
                ),
            ],
            "reward_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "reward_type": "product",
                        "reward_product_id": variant_ids[0],
                        "reward_product_ids": [(6, 0, variant_ids)],
                        "reward_product_qty": free_qty,
                        "required_points": buy_qty,
                        "multi_product": True,
                        "description": title[:80],
                    },
                ),
            ],
        }
    )
    tag = ",".join(
        t
        for t, p in OUTLET_TAG_POS.items()
        if p == pos_ids or (len(pos_ids) == 2 and p in pos_ids)
    )
    print(
        f"  buy {buy_qty} get {free_qty} → {title[:42]:42} "
        f"({len(variant_ids)} products) POS {pos_ids}"
    )


def create_percent_promo(
    env,
    *,
    gt_id: str,
    title: str,
    min_qty: int,
    percent: float,
    variant_ids: list[int],
    pos_ids: list[int],
    date_from: str | None,
    date_to: str | None,
) -> None:
    if not variant_ids or not pos_ids:
        return
    Program = env["loyalty.program"]
    display_name = title.strip()
    program = find_program(env, gt_id, display_name) or Program.create(
        {
            "name": display_name,
            "program_type": "promotion",
            "company_id": COMPANY_ID,
        }
    )
    program.write(
        {
            "name": display_name,
            "program_type": "promotion",
            "company_id": COMPANY_ID,
            "trigger": "auto",
            "applies_on": "current",
            "active": True,
            "pos_config_ids": [(6, 0, pos_ids)],
            "date_from": (date_from or "")[:10] or False,
            "date_to": (date_to or "")[:10] or False,
            "rule_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "product_ids": [(6, 0, variant_ids)],
                        "minimum_qty": min_qty,
                        "reward_point_amount": 1,
                        "reward_point_mode": "order",
                        "mode": "auto",
                    },
                ),
            ],
            "reward_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "reward_type": "discount",
                        "discount_mode": "percent",
                        "discount": percent,
                        "discount_applicability": "specific",
                        "discount_product_ids": [(6, 0, variant_ids)],
                        "required_points": 1,
                        "description": title[:80],
                    },
                ),
            ],
        }
    )
    print(
        f"  {percent:.0f}% off (min {min_qty}) → {title[:42]:42} "
        f"({len(variant_ids)} products) POS {pos_ids}"
    )


def sync_external_promotions(env, data: dict) -> None:
    promos = data.get("live_external_promotions") or []
    if not promos:
        promos = [
            p
            for p in data.get("external_promotions", [])
            if p.get("active") and p.get("supports_pos")
        ]
    print(f"\nProduct promotions ({len(promos)}):")
    for promo in promos:
        gt_id = promo.get("id", "")
        title = display_name_from_promo(promo)
        pos_ids = pos_ids_for_promo(promo)
        if not pos_ids:
            print(f"  skip {title[:40]}: no POS mapping for tags {promo.get('outlet_tags')}")
            continue
        variant_ids = resolve_variant_ids(env, promo)
        if not variant_ids:
            print(f"  skip {title[:40]}: no Odoo POS products matched")
            continue
        date_from = promo.get("start_datetime")
        date_to = promo.get("end_datetime")

        m = BUY_GET_FREE.search(title or "")
        if m:
            buy_qty = int(m.group(1))
            free_qty = int(m.group(2))
            create_buy_x_get_y(
                env,
                gt_id=gt_id,
                title=title,
                buy_qty=buy_qty,
                free_qty=free_qty,
                variant_ids=variant_ids,
                pos_ids=pos_ids,
                date_from=date_from,
                date_to=date_to,
            )
            continue

        cond = promo.get("condition") or {}
        if promo.get("promo_type") == "PROMO_SAVE" and cond.get("is_percentage"):
            qty = int(float(cond.get("quantity") or 1))
            pct = float(cond.get("amount") or 0)
            create_percent_promo(
                env,
                gt_id=gt_id,
                title=title,
                min_qty=qty,
                percent=pct,
                variant_ids=variant_ids,
                pos_ids=pos_ids,
                date_from=date_from,
                date_to=date_to,
            )
            continue

        print(f"  skip {title[:40]}: bundle/fixed ({promo.get('promo_type')}) — not auto-mapped")


def run(env) -> None:
    install_loyalty_modules(env)
    data = load_data()
    today = date.today().isoformat()

    sync_external_promotions(env, data)

    print("\nCoupon / button codes:")
    promo_map = {
        "HP": ("Half Price", 50.0, True),
        "BOGOF": ("Buy one get one FREE", 100.0, True),
    }
    for p in data.get("legacy_promotions", []):
        code = (p.get("promo_code") or "").strip().upper()
        if not code:
            continue
        title, disc, is_pct = promo_map.get(code, (p.get("promo_name") or code, 10.0, True))
        create_promo_code_program(
            env,
            name=title,
            code=code,
            discount=disc,
            is_percent=is_pct,
            date_to=None,
            date_from=None,
            pos_ids=[POS_MAIN, POS_HATCH],
        )

    for c in data.get("live_coupons", []):
        code = (c.get("coupon_code") or "").strip().upper()
        if not code:
            continue
        pos_ids = pos_ids_for_coupon(c)
        if not pos_ids:
            print(f"  skip {code}: unknown outlet {c.get('outlet_name')}")
            continue
        create_promo_code_program(
            env,
            name=code,
            code=code,
            discount=float(c.get("amount") or 0),
            is_percent=bool(c.get("is_percentage")),
            date_to=c.get("expires_at") or None,
            date_from=c.get("created_at", "")[:10] if c.get("created_at") else None,
            pos_ids=pos_ids,
            max_uses=int(c.get("max_uses") or 0),
        )

    for c in data.get("coupons", []):
        code = (c.get("coupon_code") or "").strip().upper()
        if not code or not c.get("supports_pos"):
            continue
        if (c.get("expires_at") or "") < today:
            continue
        outlet = c.get("outlet_name") or ""
        if "Hatch End" not in outlet:
            continue
        if any(x.get("coupon_code", "").upper() == code for x in data.get("live_coupons", [])):
            continue
        create_promo_code_program(
            env,
            name=code,
            code=code,
            discount=float(c.get("amount") or 0),
            is_percent=bool(c.get("is_percentage")),
            date_to=c.get("expires_at"),
            date_from=c.get("created_at", "")[:10] if c.get("created_at") else None,
            pos_ids=[POS_HATCH],
            max_uses=int(c.get("max_uses") or 0),
        )

    env.cr.commit()
    n = env["loyalty.program"].search_count([("pos_config_ids", "in", [POS_MAIN, POS_HATCH])])
    print(f"\nDone. {n} loyalty programs on Main + Hatch POS.")
    print("Close/reopen both POS sessions (Main /ui/9, Hatch /ui/13).")
    print("Buy X Get Y applies automatically; coupon codes via Enter Code at POS.")
    print("Branch prices: Rayners pricelist 1, Hatch pricelist 5 (sync with goodtill_to_odoo --sync-pricelist).")


if "env" in dir():
    run(env)
