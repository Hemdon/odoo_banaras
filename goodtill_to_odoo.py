#!/usr/bin/env python3
"""
Goodtill → Odoo product sync (Banaras Paan)

Fetches products/categories from Goodtill API and creates/updates
product.template records in Odoo (POS-ready).

Usage:
  python3 goodtill_to_odoo.py --preview          # show what would sync
  python3 goodtill_to_odoo.py --sync             # import/update products
  python3 goodtill_to_odoo.py --sync-images      # download Goodtill images → Odoo
  python3 goodtill_to_odoo.py --sync --sync-images   # products + images
  python3 goodtill_to_odoo.py --sync-taxes           # match Goodtill VAT → Odoo taxes only
  python3 goodtill_to_odoo.py --sync-pricelist       # outlet prices → ODOO_PRICELIST_ID
  GOODTILL_OUTLET_ID=e06f19a1-... ODOO_PRICELIST_ID=5 python3 goodtill_to_odoo.py --sync-pricelist --sync-taxes
  python3 goodtill_to_odoo.py --sync-images --limit 20

Env vars (or .env file in same directory):
  GOODTILL_SUBDOMAIN, GOODTILL_USERNAME, GOODTILL_PASSWORD
  ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD
  ODOO_COMPANY_ID (Banaras Paan company id, default 4 — sets product company for GBP)
  ODOO_PRICELIST_ID (for --sync-pricelist, e.g. 5 = Hatch End GBP)
  GOODTILL_OUTLET_ID (optional filter — use Hatch End UUID for branch prices/VAT)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xmlrpc.client
from pathlib import Path

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


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def download_image_bytes(url: str, token: str | None = None, timeout: int = 45) -> bytes | None:
    """Download raw image bytes from S3 URL or Goodtill API."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if not data or "image" not in ctype and not url.endswith((".jpg", ".jpeg", ".png", ".webp")):
                if data[:1] == b"{":
                    return None
            return data
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError:
        return None


def goodtill_product_image(token: str, product: dict) -> bytes | None:
    """Fetch product image from Goodtill (S3 URL or API fallback)."""
    image_url = (product.get("image") or "").strip()
    if image_url and image_url.startswith("http"):
        data = download_image_bytes(image_url)
        if data:
            return data
    pid = product.get("id")
    if not pid:
        return None
    api_url = f"https://api.thegoodtill.com/api/products/{pid}/image.jpg"
    return download_image_bytes(api_url, token=token)


def find_odoo_product_id(models, db, uid, password, product: dict) -> int | None:
    ref = gt_ref(product["id"])
    sku = (product.get("product_sku") or "").strip()
    name = (product.get("product_name") or "").strip()
    domain = [
        "|",
        "|",
        ("default_code", "=", ref),
        ("default_code", "=", sku) if sku else ("id", "=", -1),
        ("name", "=", name),
    ]
    ids = odoo_execute(
        models, db, uid, password, "product.template", "search", args=[domain], limit=1
    )
    return ids[0] if ids else None


def goodtill_request(
    path: str,
    token: str | None = None,
    body: dict | None = None,
    outlet_id: str | None = None,
) -> dict:
    url = f"https://api.thegoodtill.com/api/{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if outlet_id:
        headers["Outlet-Id"] = outlet_id
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:500]
        raise RuntimeError(f"Goodtill HTTP {e.code} for {path}: {raw}") from e


def goodtill_login() -> str:
    payload = {
        "subdomain": env("GOODTILL_SUBDOMAIN"),
        "username": env("GOODTILL_USERNAME"),
        "password": env("GOODTILL_PASSWORD"),
    }
    res = goodtill_request("login", body=payload)
    token = res.get("token")
    if not token:
        raise RuntimeError(f"Goodtill login failed: {res}")
    return token


def goodtill_fetch_all(token: str, resource: str, outlet_id: str | None = None) -> list:
    """
    Fetch a Goodtill list resource.

    For `products`, pass outlet_id so `selling_price` reflects that branch
    (shareable products have different prices per outlet).
    """
    res = goodtill_request(resource, token=token, outlet_id=outlet_id)
    rows = res.get("data") if isinstance(res, dict) else res
    return rows if isinstance(rows, list) else []


def goodtill_fetch_vat_rates(token: str) -> dict[str, dict]:
    """Return Goodtill VAT rates keyed by id."""
    rows = goodtill_fetch_all(token, "vat_rates")
    return {r["id"]: r for r in rows}


def goodtill_product_vat(token: str, product_id: str) -> tuple[float, str | None, str]:
    """
    Fetch effective VAT for a product (list endpoint omits resolved VAT).

    Returns (vat_rate_percent, vat_code_id, vat_name).
    """
    res = goodtill_request(f"products/{product_id}", token=token)
    item = res.get("data", res) if isinstance(res, dict) else res
    vat_code_id = item.get("vat_code_id")
    vat_rate = float(item.get("vat_rate") or 0)
    vat_name = (item.get("vat_name") or "").strip()
    if not vat_name and vat_code_id:
        # fallback: resolve via takeaway/oc codes on list payload
        for key in ("takeaway_vat_code", "oc_collection_vat_code", "oc_delivery_vat_code"):
            if item.get(key):
                vat_code_id = item[key]
                break
    return vat_rate, vat_code_id, vat_name


def build_odoo_tax_map(models, db: str, uid: int, password: str, company_id: int) -> dict[float, int]:
    """Map VAT percent → Odoo sale tax id for the given company."""
    taxes = odoo_execute(
        models,
        db,
        uid,
        password,
        "account.tax",
        "search_read",
        args=[[("type_tax_use", "=", "sale"), ("company_id", "=", company_id), ("active", "=", True)]],
        fields=["id", "name", "amount"],
    )
    by_amount: dict[float, int] = {}
    for t in taxes:
        amt = round(float(t["amount"]), 3)
        # Prefer plain "0%" over "Exempt" / "0% RC" for zero rate
        if amt not in by_amount or t["name"] in ("0%", "5%", "20%"):
            by_amount[amt] = t["id"]
    # UK legacy Goodtill rates → nearest current Odoo rate
    if 20.0 in by_amount:
        for legacy in (15.0, 17.5):
            by_amount.setdefault(legacy, by_amount[20.0])
    return by_amount


def resolve_odoo_tax_id(
    vat_rate: float,
    vat_code_id: str | None,
    gt_rates: dict[str, dict],
    tax_by_amount: dict[float, int],
) -> int | None:
    rate = round(float(vat_rate), 3)
    if rate in tax_by_amount:
        return tax_by_amount[rate]
    if vat_code_id and vat_code_id in gt_rates:
        gt_rate = round(float(gt_rates[vat_code_id]["vat_rate"]), 3)
        return tax_by_amount.get(gt_rate)
    return tax_by_amount.get(0.0)


def gt_ref(product_id: str) -> str:
    return f"{GT_REF_PREFIX}{product_id}"


def is_fee_or_system(name: str) -> bool:
    n = name.lower()
    skip = ("txn charge", "service charge", "gratuity", "discount", "void", "test product")
    return any(s in n for s in skip)


def pos_category_name(goodtill_cname: str, product_name: str) -> str:
    """Map Goodtill category to Odoo POS category (split Bubble Tea like the till)."""
    if goodtill_cname != "Bubble Tea":
        return goodtill_cname or "MISC"
    n = (product_name or "").lower()
    if "milk tea" in n:
        return "Bubble Milk Tea"
    if "fruit tea" in n:
        return "Bubble Fruit Tea"
    milk_hints = (
        "taro", "matcha", "brown sugar", "tiger boba", "chocolate milk", "coconut milk",
        "honeydew", "boba milk", "ginger milk", "banana milk", "strawberry milk", "mango milk",
    )
    if any(h in n for h in milk_hints):
        return "Bubble Milk Tea"
    return "Bubble Fruit Tea"


def odoo_connect():
    url = env("ODOO_URL", "http://187.77.99.211:8069").rstrip("/")
    if "srv1649615" in url and ":8069" not in url:
        url = "http://187.77.99.211:8069"
    db = env("ODOO_DB", "Main_Banaras")
    user = env("ODOO_USERNAME")
    password = env("ODOO_PASSWORD")
    if not user or not password:
        raise RuntimeError("Set ODOO_USERNAME and ODOO_PASSWORD")

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, password, {})
    if not uid:
        raise RuntimeError("Odoo authentication failed")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return db, uid, password, models


def odoo_execute(models, db, uid, password, model, method, args=None, **kwargs):
    """Call Odoo execute_kw. `args` is the positional-args list (e.g. [[domain]] for search)."""
    return models.execute_kw(db, uid, password, model, method, args or [], kwargs)


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")

    parser = argparse.ArgumentParser(description="Sync Goodtill products to Odoo")
    parser.add_argument("--preview", action="store_true", help="Preview only, no Odoo writes")
    parser.add_argument("--sync", action="store_true", help="Create/update products in Odoo")
    parser.add_argument("--sync-images", action="store_true", help="Download Goodtill images into Odoo products")
    parser.add_argument("--sync-taxes", action="store_true", help="Match Goodtill VAT rates to Odoo product taxes")
    parser.add_argument(
        "--sync-pricelist",
        action="store_true",
        help="Sync selling_price to ODOO_PRICELIST_ID (branch-specific prices)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max products to process (0=all)")
    parser.add_argument("--delay", type=float, default=0.15, help="Seconds between image uploads")
    args = parser.parse_args()

    if not args.preview and not args.sync and not args.sync_images and not args.sync_taxes and not args.sync_pricelist:
        parser.print_help()
        return 1

    print("Logging in to Goodtill...")
    token = goodtill_login()
    print("  OK")

    outlet_filter = env("GOODTILL_OUTLET_ID")
    # Outlet-Id header is required for correct per-branch selling_price on shareable products
    products = goodtill_fetch_all(token, "products", outlet_id=outlet_filter or None)
    categories = goodtill_fetch_all(token, "categories")
    outlets = goodtill_fetch_all(token, "outlets")
    cat_by_id = {c["id"]: c for c in categories}

    print("\nGoodtill outlets:")
    for o in outlets:
        mark = " <-- filter" if outlet_filter and o["id"] == outlet_filter else ""
        print(f"  - {o.get('outlet_name')} ({o.get('store_tag')}){mark}")

    # Active sellable products (top-level rows and priced variants, e.g. ICE Cream scoops)
    candidates = []
    for p in products:
        if not p.get("active"):
            continue
        if is_fee_or_system(p.get("product_name", "")):
            continue
        # When filtering by outlet: include shareable products + this outlet's products
        if outlet_filter:
            if not p.get("shareable") and p.get("outlet_id") != outlet_filter:
                continue
        price = float(p.get("selling_price") or 0)
        is_open = p.get("is_open_price_product")
        if not p.get("top_level_product"):
            # Variant rows only when they have an outlet price (parent shells are £0)
            if price <= 0 and not is_open:
                continue
        elif price <= 0 and not is_open:
            continue
        candidates.append(p)

    if args.limit:
        candidates = candidates[: args.limit]

    print(f"\nProducts to sync: {len(candidates)} (from {len(products)} total)")
    by_cat: dict[str, int] = {}
    for p in candidates:
        cid = p.get("category_id") or "none"
        cname = (cat_by_id.get(cid) or {}).get("name", "Uncategorised")
        by_cat[cname] = by_cat.get(cname, 0) + 1
    print("By category:")
    for name, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {count:3d}  {name}")

    with_images = [p for p in candidates if p.get("image")]
    print(f"Products with images: {len(with_images)} / {len(candidates)}")

    if args.preview:
        print("\nSample (first 10):")
        gt_rates = goodtill_fetch_vat_rates(token)
        for p in candidates[:10]:
            cid = p.get("category_id")
            cname = (cat_by_id.get(cid) or {}).get("name", "?")
            img = "yes" if p.get("image") else "no"
            try:
                vr, vc, vn = goodtill_product_vat(token, p["id"])
                vat_label = vn or gt_rates.get(vc or "", {}).get("vat_name") or f"{vr:g}%"
            except Exception:
                vat_label = "?"
            print(
                f"  {p.get('product_name')[:36]:36} £{p.get('selling_price'):>6}  "
                f"VAT={vat_label:8}  [{cname}]  img={img}"
            )
        if outlet_filter:
            print(f"\n(Prices shown are for outlet {outlet_filter} via Goodtill Outlet-Id header.)")
        print("\nPreview complete. Run with --sync, --sync-taxes, or --sync-images to import.")
        return 0

    if args.sync_pricelist and not args.sync:
        rc = sync_pricelist_only(token, candidates, args)
        if args.sync_taxes:
            return sync_taxes_only(token, candidates, args)
        return rc

    if args.sync_taxes and not args.sync:
        return sync_taxes_only(token, candidates, args)

    if args.sync_images and not args.sync:
        return sync_images_only(token, candidates, args)

    print("\nConnecting to Odoo...")
    db, uid, password, models = odoo_connect()
    print(f"  Authenticated uid={uid}")

    company_id = int(env("ODOO_COMPANY_ID", "4"))
    gt_rates = goodtill_fetch_vat_rates(token)
    tax_by_amount = build_odoo_tax_map(models, db, uid, password, company_id)
    print(f"  Odoo tax map (% → id): {tax_by_amount}")

    # POS categories keyed by Goodtill category name
    pos_cat_ids = odoo_execute(
        models, db, uid, password, "pos.category", "search", args=[[("id", ">", 0)]]
    )
    pos_cats = (
        odoo_execute(
            models,
            db,
            uid,
            password,
            "pos.category",
            "read",
            args=[pos_cat_ids],
            fields=["id", "name"],
        )
        if pos_cat_ids
        else []
    )
    pos_cat_by_name = {}
    for c in pos_cats:
        name = c["name"] if isinstance(c["name"], str) else c["name"].get("en_GB") or c["name"].get("en_US")
        pos_cat_by_name[name] = c["id"]

    created = updated = skipped = 0

    for p in candidates:
        name = (p.get("product_name") or "").strip()
        if not name:
            skipped += 1
            continue

        ref = gt_ref(p["id"])
        sku = (p.get("product_sku") or "").strip()
        default_code = sku or ref
        price = float(p.get("selling_price") or 0)
        cid = p.get("category_id")
        gt_cname = (cat_by_id.get(cid) or {}).get("name", "MISC")
        cname = pos_category_name(gt_cname, name)

        if cname not in pos_cat_by_name:
            new_id = odoo_execute(
                models,
                db,
                uid,
                password,
                "pos.category",
                "create",
                args=[{"name": cname}],
            )
            pos_cat_by_name[cname] = new_id
            print(f"  + POS category: {cname}")

        pos_categ_id = pos_cat_by_name[cname]

        # Match existing: GT ref in default_code, SKU, or exact name
        domain = [
            "|",
            "|",
            ("default_code", "=", ref),
            ("default_code", "=", sku) if sku else ("id", "=", -1),
            ("name", "=", name),
        ]
        existing_ids = odoo_execute(
            models,
            db,
            uid,
            password,
            "product.template",
            "search",
            args=[domain],
            limit=1,
        )

        desc = f"Synced from Goodtill. Outlet: {p.get('outlet_id', '')}. Category: {cname}."
        vat_rate, vat_code_id, vat_name = goodtill_product_vat(token, p["id"])
        tax_id = resolve_odoo_tax_id(vat_rate, vat_code_id, gt_rates, tax_by_amount)
        vals = {
            "name": name,
            "list_price": price,
            "default_code": default_code,
            "company_id": company_id,
            "available_in_pos": True,
            "sale_ok": True,
            "type": "consu",
            "description_sale": desc,
            "pos_categ_ids": [(6, 0, [pos_categ_id])],
        }
        if tax_id:
            vals["taxes_id"] = [(6, 0, [tax_id])]
        elif tax_id is None:
            print(f"  ! No Odoo tax for {name[:30]} (Goodtill {vat_rate}% / {vat_name})")

        if existing_ids:
            odoo_execute(
                models,
                db,
                uid,
                password,
                "product.template",
                "write",
                args=[existing_ids, vals],
            )
            updated += 1
        else:
            odoo_execute(
                models, db, uid, password, "product.template", "create", args=[vals]
            )
            created += 1

    print(f"\nSync complete: created={created}, updated={updated}, skipped={skipped}")

    if args.sync_images:
        print("\n--- Image sync ---")
        img_stats = upload_images(token, models, db, uid, password, candidates, args.delay)
        print(
            f"Images: uploaded={img_stats['uploaded']}, skipped={img_stats['skipped']}, "
            f"no_odoo={img_stats['no_odoo']}, failed={img_stats['failed']}"
        )
    return 0


def upload_images(
    token: str,
    models,
    db: str,
    uid: int,
    password: str,
    candidates: list,
    delay: float,
) -> dict:
    uploaded = skipped = no_odoo = failed = 0
    for i, p in enumerate(candidates, 1):
        name = (p.get("product_name") or "").strip()
        if not p.get("image"):
            skipped += 1
            continue

        odoo_id = find_odoo_product_id(models, db, uid, password, p)
        if not odoo_id:
            no_odoo += 1
            print(f"  [{i}] {name[:35]:35} — no Odoo match")
            continue

        img_bytes = goodtill_product_image(token, p)
        if not img_bytes or len(img_bytes) < 100:
            failed += 1
            print(f"  [{i}] {name[:35]:35} — download failed")
            continue

        b64 = base64.b64encode(img_bytes).decode("ascii")
        try:
            # Write image; include list_price touch so write_date changes (POS cache bust)
            odoo_data = odoo_execute(
                models, db, uid, password, "product.template", "read",
                args=[[odoo_id]], fields=["list_price"],
            )
            lp = odoo_data[0]["list_price"] if odoo_data else 0
            odoo_execute(
                models,
                db,
                uid,
                password,
                "product.template",
                "write",
                args=[[odoo_id], {"image_1920": b64, "list_price": lp}],
            )
            uploaded += 1
            if uploaded <= 5 or uploaded % 25 == 0:
                print(f"  [{i}] {name[:35]:35} — OK ({len(img_bytes)//1024} KB)")
        except Exception as e:
            failed += 1
            print(f"  [{i}] {name[:35]:35} — Odoo error: {str(e)[:80]}")

        if delay:
            time.sleep(delay)
    return {"uploaded": uploaded, "skipped": skipped, "no_odoo": no_odoo, "failed": failed}


def sync_pricelist_only(token: str, candidates: list, args) -> int:
    pl_id = int(env("ODOO_PRICELIST_ID", "0"))
    if not pl_id:
        print("Set ODOO_PRICELIST_ID (e.g. 5 for Hatch End GBP)")
        return 1

    print("\nConnecting to Odoo...")
    db, uid, password, models = odoo_connect()
    print(f"  Authenticated uid={uid}")
    pl = odoo_execute(
        models, db, uid, password, "product.pricelist", "read", args=[[pl_id]], fields=["name", "company_id"]
    )
    if not pl:
        print(f"Pricelist id={pl_id} not found")
        return 1
    print(f"  Target pricelist: {pl[0]['name']} (id={pl_id})")

    created = updated = skipped = no_match = 0
    for i, p in enumerate(candidates, 1):
        name = (p.get("product_name") or "").strip()
        price = float(p.get("selling_price") or 0)
        if not name or price <= 0:
            skipped += 1
            continue

        odoo_id = find_odoo_product_id(models, db, uid, password, p)
        if not odoo_id:
            no_match += 1
            continue

        item_ids = odoo_execute(
            models,
            db,
            uid,
            password,
            "product.pricelist.item",
            "search",
            args=[[("pricelist_id", "=", pl_id), ("product_tmpl_id", "=", odoo_id)]],
            limit=1,
        )
        vals = {
            "pricelist_id": pl_id,
            "product_tmpl_id": odoo_id,
            "applied_on": "1_product",
            "compute_price": "fixed",
            "fixed_price": price,
        }
        if item_ids:
            odoo_execute(
                models, db, uid, password, "product.pricelist.item", "write", args=[[item_ids[0]], vals]
            )
            updated += 1
        else:
            odoo_execute(models, db, uid, password, "product.pricelist.item", "create", args=[vals])
            created += 1

        if (created + updated) <= 5 or (created + updated) % 50 == 0:
            print(f"  [{i}] {name[:35]:35} £{price:.2f}")

        if args.delay:
            time.sleep(min(args.delay, 0.05))

    print(
        f"\nPricelist sync complete: created={created}, updated={updated}, "
        f"skipped={skipped}, no_odoo_match={no_match}"
    )
    return 0


def sync_taxes_only(token: str, candidates: list, args) -> int:
    print("\nConnecting to Odoo...")
    db, uid, password, models = odoo_connect()
    print(f"  Authenticated uid={uid}")

    company_id = int(env("ODOO_COMPANY_ID", "4"))
    gt_rates = goodtill_fetch_vat_rates(token)
    tax_by_amount = build_odoo_tax_map(models, db, uid, password, company_id)
    print(f"  Odoo tax map (% → id): {tax_by_amount}")

    updated = skipped = no_match = no_tax = 0
    vat_stats: dict[str, int] = {}

    for i, p in enumerate(candidates, 1):
        name = (p.get("product_name") or "").strip()
        odoo_id = find_odoo_product_id(models, db, uid, password, p)
        if not odoo_id:
            no_match += 1
            continue

        try:
            vat_rate, vat_code_id, vat_name = goodtill_product_vat(token, p["id"])
        except Exception as e:
            print(f"  [{i}] {name[:35]:35} — Goodtill VAT fetch failed: {e}")
            skipped += 1
            continue

        tax_id = resolve_odoo_tax_id(vat_rate, vat_code_id, gt_rates, tax_by_amount)
        if not tax_id:
            no_tax += 1
            print(f"  [{i}] {name[:35]:35} — no Odoo tax for {vat_rate}%")
            continue

        label = vat_name or gt_rates.get(vat_code_id or "", {}).get("vat_name") or f"{vat_rate:g}%"
        vat_stats[label] = vat_stats.get(label, 0) + 1

        odoo_execute(
            models,
            db,
            uid,
            password,
            "product.template",
            "write",
            args=[[odoo_id], {"taxes_id": [(6, 0, [tax_id])]}],
        )
        updated += 1
        if updated <= 5 or updated % 50 == 0:
            print(f"  [{i}] {name[:35]:35} → {label}")

        if args.delay:
            time.sleep(min(args.delay, 0.2))

    print(f"\nTax sync complete: updated={updated}, no_odoo_match={no_match}, skipped={skipped}, no_tax={no_tax}")
    print("Goodtill VAT breakdown:")
    for label, count in sorted(vat_stats.items(), key=lambda x: -x[1]):
        print(f"  {count:3d}  {label}")
    return 0


def sync_images_only(token: str, candidates: list, args) -> int:
    print("\nConnecting to Odoo...")
    db, uid, password, models = odoo_connect()
    print(f"  Authenticated uid={uid}")
    stats = upload_images(token, models, db, uid, password, candidates, args.delay)
    print(
        f"\nImage sync complete: uploaded={stats['uploaded']}, skipped={stats['skipped']}, "
        f"no_odoo={stats['no_odoo']}, failed={stats['failed']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
