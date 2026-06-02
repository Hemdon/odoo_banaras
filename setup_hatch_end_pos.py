#!/usr/bin/env python3
"""
Configure Hatch End POS (Banaras - Hatch End / Goodtill Hatch End outlet).

- GBP pricelist for company 6 with outlet-specific prices from Goodtill
- POS config "Hatch End Register" with same category set as Rayners Lane
- Payment methods using parent company (Banaras Paan) cash/sale journals

Run on server:
  sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d Main_Banaras --no-http < setup_hatch_end_pos.py

Or from laptop (needs ODOO_URL pointing at 187.77.99.211):
  python3 setup_hatch_end_pos.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
import xmlrpc.client
from pathlib import Path

HATCH_COMPANY = "Banaras - Hatch End"
HATCH_COMPANY_ID = 6
PAAN_COMPANY_ID = 4
POS_NAME = "Hatch End Register"
GOODTILL_OUTLET_ID = "e06f19a1-d9f9-4578-85b6-56d5adb580e5"
PRICELIST_NAME = "Hatch End (GBP)"

GOODTILL_CATEGORIES = [
    "Paan", "Bubble Fruit Tea", "Bubble Milk Tea", "Freeze Drinks", "Paan Masala", "Paan Mukhwas",
    "Sweets and Candy", "Mocktails", "MISC", "Indian Stuffs", "Thick Milk Shake",
    "Banaras Hot Drinks", "Falooda", "Drinks", "ICE Gola", "ICE Creams", "Hot Drinks",
    "TBC", "Chakhna", "Thandai",
]

GT_REF_PREFIX = "GT:"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def cat_display_name(name_field) -> str:
    if isinstance(name_field, str):
        return name_field
    if isinstance(name_field, dict):
        return name_field.get("en_GB") or name_field.get("en_US") or next(iter(name_field.values()), "")
    return str(name_field)


# --- Goodtill (optional price sync) ---

def goodtill_login() -> str:
    payload = {
        "subdomain": cfg("GOODTILL_SUBDOMAIN"),
        "username": cfg("GOODTILL_USERNAME"),
        "password": cfg("GOODTILL_PASSWORD"),
    }
    req = urllib.request.Request(
        "https://api.thegoodtill.com/api/login",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        res = json.loads(resp.read())
    token = res.get("token")
    if not token:
        raise RuntimeError(f"Goodtill login failed: {res}")
    return token


def goodtill_fetch(token: str, resource: str) -> list:
    req = urllib.request.Request(
        f"https://api.thegoodtill.com/api/{resource}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        res = json.loads(resp.read())
    rows = res.get("data") if isinstance(res, dict) else res
    return rows if isinstance(rows, list) else []


def is_fee_or_system(name: str) -> bool:
    n = name.lower()
    return any(s in n for s in ("txn charge", "service charge", "gratuity", "discount", "void", "test product"))


def hatch_end_products(token: str) -> list[dict]:
    products = goodtill_fetch(token, "products")
    out = []
    for p in products:
        if not p.get("active") or not p.get("top_level_product"):
            continue
        if is_fee_or_system(p.get("product_name", "")):
            continue
        if not p.get("shareable") and p.get("outlet_id") != GOODTILL_OUTLET_ID:
            continue
        price = float(p.get("selling_price") or 0)
        if price <= 0 and not p.get("is_open_price_product"):
            continue
        out.append(p)
    return out


# --- Odoo shell (in-process) or XML-RPC ---

def setup_in_odoo_shell(env) -> int:
    logging.getLogger("odoo").setLevel(logging.ERROR)

    hatch = env["res.company"].search([("name", "=", HATCH_COMPANY)], limit=1)
    if not hatch:
        print(f"Company not found: {HATCH_COMPANY}")
        return 1

    paan = env["res.company"].browse(PAAN_COMPANY_ID)
    gbp = env.ref("base.GBP")

    sale_j = env["account.journal"].search([("company_id", "=", paan.id), ("type", "=", "sale")], limit=1)
    bank_j = env["account.journal"].search([("company_id", "=", paan.id), ("type", "=", "bank")], limit=1)
    if not sale_j:
        print("Missing sale journal on Banaras Paan — run UK chart setup first")
        return 1

    # Each POS needs its own cash journal (Odoo forbids sharing cash journal across POS)
    cash_j = env["account.journal"].search([("company_id", "=", paan.id), ("code", "=", "CSH2")], limit=1)
    if not cash_j:
        cash_acct = env["account.account"].with_company(paan).search(
            [("code", "=like", "1210%")], limit=1
        ) or env["account.account"].with_company(paan).search(
            [("account_type", "=", "asset_cash")], limit=1
        )
        cash_j = env["account.journal"].create({
            "name": "Cash Hatch End",
            "code": "CSH2",
            "type": "cash",
            "company_id": paan.id,
            "default_account_id": cash_acct.id,
        })
        print(f"Created cash journal {cash_j.code}")

    if not hatch.chart_template:
        hatch.chart_template = "uk"

    wh = env["stock.warehouse"].search([("company_id", "=", hatch.id)], limit=1)
    if not wh:
        wh = env["stock.warehouse"].create({
            "name": "Hatch End",
            "code": "HE",
            "company_id": hatch.id,
        })
        print(f"Created warehouse {wh.name} (id={wh.id})")

    pl = env["product.pricelist"].search([("company_id", "=", hatch.id)], limit=1)
    if pl:
        pl.write({"name": PRICELIST_NAME, "currency_id": gbp.id})
    else:
        pl = env["product.pricelist"].create({
            "name": PRICELIST_NAME,
            "currency_id": gbp.id,
            "company_id": hatch.id,
        })
    print(f"Pricelist: {pl.name} (id={pl.id})")

    cats = env["pos.category"].search([("name", "in", GOODTILL_CATEGORIES)])
    categ_ids = cats.ids

    pos = env["pos.config"].search([("company_id", "=", hatch.id)], limit=1)
    cash_pm = env["pos.payment.method"].search([
        ("company_id", "=", hatch.id), ("name", "ilike", "cash"),
    ], limit=1)
    card_pm = env["pos.payment.method"].search([
        ("company_id", "=", hatch.id), ("name", "ilike", "card"),
    ], limit=1)

    if not cash_pm:
        cash_pm = env["pos.payment.method"].create({
            "name": "Cash",
            "journal_id": cash_j.id,
            "company_id": hatch.id,
        })
    else:
        cash_pm.journal_id = cash_j.id

    if not bank_j:
        print("Warning: no bank journal on Banaras Paan — Card will use Sales journal")
        bank_j = sale_j
    if not card_pm:
        card_pm = env["pos.payment.method"].create({
            "name": "Card",
            "journal_id": bank_j.id,
            "company_id": hatch.id,
        })
    else:
        card_pm.journal_id = bank_j.id

    pos_vals = {
        "name": POS_NAME,
        "company_id": hatch.id,
        "warehouse_id": wh.id,
        "journal_id": cash_j.id,
        "invoice_journal_id": sale_j.id,
        "use_pricelist": True,
        "pricelist_id": pl.id,
        "available_pricelist_ids": [(6, 0, [pl.id])],
        "currency_id": gbp.id,
        "payment_method_ids": [(6, 0, [cash_pm.id, card_pm.id])],
        "limit_categories": True,
        "iface_available_categ_ids": [(6, 0, categ_ids)],
        "iface_group_by_categ": True,
        "show_product_images": True,
        "show_category_images": True,
        "iface_tax_included": "total",
        "receipt_header": "Banaras Paan\nHatch End",
        "receipt_footer": "Thank you!\nbanaraspaan.com",
    }

    if pos:
        pos.write(pos_vals)
        print(f"Updated POS config id={pos.id}")
    else:
        pos = env["pos.config"].create(pos_vals)
        print(f"Created POS config id={pos.id}")

    pos._compute_company_has_template()
    env.cr.commit()

    print(f"\nCompany: {hatch.name} (id={hatch.id})")
    print(f"POS: {pos.name} (id={pos.id})")
    print(f"Categories: {len(categ_ids)}")
    print(f"company_has_template: {pos.company_has_template}")
    return pos.id, pl.id


def sync_pricelist_items_shell(env, pos_id: int, pl_id: int) -> None:
    """Set fixed prices on Hatch End pricelist from Goodtill outlet products."""
    try:
        token = goodtill_login()
    except (urllib.error.URLError, RuntimeError) as e:
        print(f"Skipping Goodtill price sync: {e}")
        return

    products = hatch_end_products(token)
    pl = env["product.pricelist"].browse(pl_id)
    Product = env["product.template"]
    gt_ref = lambda pid: f"{GT_REF_PREFIX}{pid}"

    updated = created = skipped = 0
    for p in products:
        ref = gt_ref(p["id"])
        sku = (p.get("product_sku") or "").strip()
        name = (p.get("product_name") or "").strip()
        price = float(p.get("selling_price") or 0)
        if not name or price <= 0:
            skipped += 1
            continue

        tmpl = Product.search([
            "|", "|",
            ("default_code", "=", ref),
            ("default_code", "=", sku) if sku else ("id", "=", -1),
            ("name", "=", name),
        ], limit=1)
        if not tmpl:
            skipped += 1
            continue

        item = env["product.pricelist.item"].search([
            ("pricelist_id", "=", pl.id),
            ("product_tmpl_id", "=", tmpl.id),
        ], limit=1)
        if item:
            item.write({"fixed_price": price})
            updated += 1
        else:
            env["product.pricelist.item"].create({
                "pricelist_id": pl.id,
                "product_tmpl_id": tmpl.id,
                "applied_on": "1_product",
                "compute_price": "fixed",
                "fixed_price": price,
            })
            created += 1

    env.cr.commit()
    print(f"Pricelist items: created={created}, updated={updated}, skipped={skipped} (from {len(products)} GT products)")


def setup_via_xmlrpc() -> int:
    load_dotenv(Path(__file__).parent / ".env")
    url = cfg("ODOO_URL", "http://187.77.99.211:8069").rstrip("/")
    if "srv1649615" in url and "8069" not in url:
        url = "http://187.77.99.211:8069"
    db, user, password = cfg("ODOO_DB", "Main_Banaras"), cfg("ODOO_USERNAME"), cfg("ODOO_PASSWORD")

    # Run remote shell script via SSH is preferred; xmlrpc can't run shell logic easily.
    # Upload and execute on server.
    print("Use server shell: sudo -u odoo odoo shell -d Main_Banaras --no-http < setup_hatch_end_pos.py")
    return 1


def run_all(env) -> int:
    pos_id, pl_id = setup_in_odoo_shell(env)
    sync_pricelist_items_shell(env, pos_id, pl_id)
    base = env["ir.config_parameter"].sudo().get_param("web.base.url") or "http://187.77.99.211:8069"
    print(f"\nOpen POS: {base.rstrip('/')}/pos/ui/{pos_id}")
    print(f"Goodtill outlet: {GOODTILL_OUTLET_ID}")
    return 0


def _odoo_env():
    try:
        return env  # noqa: F821 — Odoo Environment in shell
    except NameError:
        return None


_oenv = _odoo_env()
if _oenv is not None:
    run_all(_oenv)
elif __name__ == "__main__":
    sys.exit(setup_via_xmlrpc())
