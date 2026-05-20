#!/usr/bin/env python3
"""
Fix POS product images: re-sync from Goodtill, set category images, refresh POS cache.

Usage:
  python3 fix_pos_images.py
  python3 fix_pos_images.py --limit 20
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
import urllib.error
import urllib.request
import xmlrpc.client
from pathlib import Path

# Reuse helpers from main sync script
sys.path.insert(0, str(Path(__file__).parent))
from goodtill_to_odoo import (  # noqa: E402
    GT_REF_PREFIX,
    download_image_bytes,
    env,
    find_odoo_product_id,
    goodtill_fetch_all,
    goodtill_login,
    goodtill_product_image,
    gt_ref,
    is_fee_or_system,
    load_dotenv,
    odoo_connect,
    odoo_execute,
)

MAIN_REGISTER_CATEGORIES = [
    "Paan", "Bubble Tea", "Freeze Drinks", "Paan Masala", "Paan Mukhwas",
    "Sweets and Candy", "Mocktails", "MISC", "Indian Stuffs", "Thick Milk Shake",
    "Banaras Hot Drinks", "Falooda", "Drinks", "ICE Gola", "Hot Drinks",
    "TBC", "Chakhna", "Thandai",
]


def get_candidates(products: list) -> list:
    outlet_filter = env("GOODTILL_OUTLET_ID")
    cat_by_id = {}
    out = []
    for p in products:
        if not p.get("active") or not p.get("top_level_product"):
            continue
        if is_fee_or_system(p.get("product_name", "")):
            continue
        if outlet_filter:
            if not p.get("shareable") and p.get("outlet_id") != outlet_filter:
                continue
        price = float(p.get("selling_price") or 0)
        if price <= 0 and not p.get("is_open_price_product"):
            continue
        if p.get("image"):
            out.append(p)
    return out


def sync_product_images(token, models, db, uid, password, candidates: list, delay: float) -> int:
    uploaded = 0
    for i, p in enumerate(candidates, 1):
        odoo_id = find_odoo_product_id(models, db, uid, password, p)
        if not odoo_id:
            continue
        img_bytes = goodtill_product_image(token, p)
        if not img_bytes or len(img_bytes) < 100:
            continue
        b64 = base64.b64encode(img_bytes).decode("ascii")
        odoo_execute(
            models, db, uid, password, "product.template", "write",
            args=[[odoo_id], {"image_1920": b64}],
        )
        uploaded += 1
        if uploaded <= 3 or uploaded % 30 == 0:
            name = (p.get("product_name") or "")[:35]
            print(f"  product [{uploaded}] {name} ({len(img_bytes)//1024} KB)")
        if delay:
            time.sleep(delay)
    return uploaded


def sync_category_images(models, db, uid, password) -> int:
    """Set pos.category image from first product in category that has an image."""
    updated = 0
    for cname in MAIN_REGISTER_CATEGORIES:
        cat_ids = odoo_execute(
            models, db, uid, password, "pos.category", "search",
            args=[[("name", "=", cname)]], limit=1,
        )
        if not cat_ids:
            continue
        cat_id = cat_ids[0]
        pt_ids = odoo_execute(
            models, db, uid, password, "product.template", "search",
            args=[[("pos_categ_ids", "in", [cat_id]), ("available_in_pos", "=", True)]],
            limit=50,
        )
        img = None
        if pt_ids:
            for pt in odoo_execute(
                models, db, uid, password, "product.template", "read",
                args=[pt_ids], fields=["image_1920"],
            ):
                if pt.get("image_1920"):
                    img = pt["image_1920"]
                    break
        if not img:
            continue
        odoo_execute(
            models, db, uid, password, "pos.category", "write",
            args=[[cat_id], {"image_128": img}],
        )
        updated += 1
        print(f"  category {cname}")
    return updated


def configure_pos(models, db, uid, password) -> int:
    rayner = odoo_execute(
        models, db, uid, password, "res.company", "search",
        args=[[("name", "=", "Banaras - RaynerLane")]], limit=1,
    )
    if not rayner:
        return 0
    pos_ids = odoo_execute(
        models, db, uid, password, "pos.config", "search",
        args=[[("company_id", "=", rayner[0])]], limit=1,
    )
    if not pos_ids:
        return 0
    cat_ids = odoo_execute(
        models, db, uid, password, "pos.category", "search",
        args=[[("name", "in", MAIN_REGISTER_CATEGORIES)]],
    )
    odoo_execute(
        models, db, uid, password, "pos.config", "write",
        args=[[pos_ids[0]], {
            "name": "Main Register",
            "show_product_images": True,
            "show_category_images": True,
            "iface_group_by_categ": True,
            "limit_categories": True,
            "iface_available_categ_ids": [(6, 0, cat_ids)],
        }],
    )
    print(f"  POS config id={pos_ids[0]} — images enabled, {len(cat_ids)} categories")
    return pos_ids[0]


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.1)
    args = parser.parse_args()

    print("Goodtill login...")
    token = goodtill_login()
    products = goodtill_fetch_all(token, "products")
    candidates = get_candidates(products)
    if args.limit:
        candidates = candidates[: args.limit]
    print(f"Products with Goodtill images: {len(candidates)}")

    print("\nOdoo login...")
    db, uid, password, models = odoo_connect()

    print("\n1) Re-sync product images...")
    n = sync_product_images(token, models, db, uid, password, candidates, args.delay)
    print(f"   Uploaded: {n}")

    print("\n2) Set category tile images...")
    c = sync_category_images(models, db, uid, password)
    print(f"   Categories: {c}")

    print("\n3) Configure POS...")
    pos_id = configure_pos(models, db, uid, password)

    print("\nDone.")
    print("IMPORTANT: Close any open POS session, then reopen:")
    print(f"  {env('ODOO_URL', 'http://46.202.140.75:8069')}/pos/ui?config_id={pos_id}")
    print("Hard refresh browser (Cmd+Shift+R) if images still missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
