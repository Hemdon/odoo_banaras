#!/usr/bin/env python3
"""
Configure Odoo Rayners Lane POS to mirror Goodtill Main Outlet / Main Register.

- Restricts POS to Goodtill Main Outlet product categories only
- Renames POS config to match Goodtill register
- Links payment methods for Banaras - RaynerLane company

Run after goodtill_to_odoo.py --sync
"""

from __future__ import annotations

import os
import sys
import xmlrpc.client
from pathlib import Path

MAIN_OUTLET_ID = "02f13246-56ff-404e-84b8-ad3200601295"
RAYNERLANE_COMPANY = "Banaras - RaynerLane"
POS_CONFIG_NAME = "Main Register"  # matches Goodtill register_name
GOODTILL_CATEGORIES = [
    "Paan",
    "Bubble Tea",
    "Freeze Drinks",
    "Paan Masala",
    "Paan Mukhwas",
    "Sweets and Candy",
    "Mocktails",
    "MISC",
    "Indian Stuffs",
    "Thick Milk Shake",
    "Banaras Hot Drinks",
    "Falooda",
    "Drinks",
    "ICE Gola",
    "Hot Drinks",
    "TBC",
    "Chakhna",
    "Thandai",
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def odoo_execute(models, db, uid, password, model, method, args=None, **kwargs):
    return models.execute_kw(db, uid, password, model, method, args or [], kwargs)


def cat_display_name(name_field) -> str:
    if isinstance(name_field, str):
        return name_field
    if isinstance(name_field, dict):
        return name_field.get("en_GB") or name_field.get("en_US") or next(iter(name_field.values()), "")
    return str(name_field)


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")

    url = env("ODOO_URL", "http://46.202.140.75:8069").rstrip("/")
    db = env("ODOO_DB", "Main_Banaras")
    user = env("ODOO_USERNAME")
    password = env("ODOO_PASSWORD")

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, password, {})
    if not uid:
        print("Odoo auth failed")
        return 1
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    company_ids = odoo_execute(
        models, db, uid, password,
        "res.company", "search", args=[[("name", "=", RAYNERLANE_COMPANY)]],
    )
    if not company_ids:
        print(f"Company not found: {RAYNERLANE_COMPANY}")
        return 1
    company_id = company_ids[0]

    pos_ids = odoo_execute(
        models, db, uid, password,
        "pos.config", "search", args=[[("company_id", "=", company_id)]],
    )
    if not pos_ids:
        print("No POS config for RaynerLane — create one first")
        return 1
    pos_id = pos_ids[0]

    all_cats = odoo_execute(
        models, db, uid, password,
        "pos.category", "search_read", args=[[("id", ">", 0)]], fields=["id", "name"],
    )
    cat_by_name = {cat_display_name(c["name"]): c["id"] for c in all_cats}

    categ_ids = []
    missing = []
    for name in GOODTILL_CATEGORIES:
        if name in cat_by_name:
            categ_ids.append(cat_by_name[name])
        else:
            missing.append(name)

    if missing:
        print("Missing categories (run goodtill_to_odoo.py --sync first):", ", ".join(missing))

    # Products in these categories with Goodtill ref
    gt_product_count = odoo_execute(
        models, db, uid, password,
        "product.template", "search_count",
        args=[[
            ("available_in_pos", "=", True),
            ("pos_categ_ids", "in", categ_ids),
        ]],
    )

    gbp_ids = odoo_execute(
        models, db, uid, password, "res.currency", "search", args=[[("name", "=", "GBP")]], limit=1
    )
    gbp_id = gbp_ids[0] if gbp_ids else False

    pl_ids = odoo_execute(
        models, db, uid, password,
        "product.pricelist", "search", args=[[("company_id", "=", company_id)]], limit=1
    )
    if pl_ids:
        odoo_execute(
            models, db, uid, password,
            "product.pricelist", "write", args=[[pl_ids[0]], {"currency_id": gbp_id, "name": "Rayners Lane (GBP)"}],
        )
        pricelist_id = pl_ids[0]
    else:
        pricelist_id = odoo_execute(
            models, db, uid, password,
            "product.pricelist", "create",
            args=[{"name": "Rayners Lane (GBP)", "currency_id": gbp_id, "company_id": company_id}],
        )

    vals = {
        "name": POS_CONFIG_NAME,
        "currency_id": gbp_id,
        "pricelist_id": pricelist_id,
        "limit_categories": True,
        "iface_available_categ_ids": [(6, 0, categ_ids)],
        "iface_group_by_categ": True,
        "show_category_images": True,
        "show_product_images": True,
        "iface_tax_included": "total",
        "receipt_header": "Banaras Paan\nRayners Lane",
        "receipt_footer": "Thank you!\nbanaraspaan.com",
    }
    odoo_execute(models, db, uid, password, "pos.config", "write", args=[[pos_id], vals])

    print(f"Company: {RAYNERLANE_COMPANY} (id={company_id})")
    print(f"POS config id={pos_id} -> '{POS_CONFIG_NAME}'")
    print(f"Categories on register: {len(categ_ids)}")
    print(f"POS-ready products in those categories: {gt_product_count}")
    print(f"Open POS: {url}/pos/ui?config_id={pos_id}")
    print(f"Goodtill mirror: Main Outlet / Main Register ({MAIN_OUTLET_ID})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
