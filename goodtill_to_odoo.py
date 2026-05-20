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
  python3 goodtill_to_odoo.py --sync-images --limit 20

Env vars (or .env file in same directory):
  GOODTILL_SUBDOMAIN, GOODTILL_USERNAME, GOODTILL_PASSWORD
  ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD
  GOODTILL_OUTLET_ID (optional filter)
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


def goodtill_request(path: str, token: str | None = None, body: dict | None = None) -> dict:
    url = f"https://api.thegoodtill.com/api/{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


def goodtill_fetch_all(token: str, resource: str) -> list:
    res = goodtill_request(resource, token=token)
    rows = res.get("data") if isinstance(res, dict) else res
    return rows if isinstance(rows, list) else []


def gt_ref(product_id: str) -> str:
    return f"{GT_REF_PREFIX}{product_id}"


def is_fee_or_system(name: str) -> bool:
    n = name.lower()
    skip = ("txn charge", "service charge", "gratuity", "discount", "void", "test product")
    return any(s in n for s in skip)


def odoo_connect():
    url = env("ODOO_URL", "http://46.202.140.75:8069").rstrip("/")
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
    parser.add_argument("--limit", type=int, default=0, help="Max products to process (0=all)")
    parser.add_argument("--delay", type=float, default=0.15, help="Seconds between image uploads")
    args = parser.parse_args()

    if not args.preview and not args.sync and not args.sync_images:
        parser.print_help()
        return 1

    print("Logging in to Goodtill...")
    token = goodtill_login()
    print("  OK")

    products = goodtill_fetch_all(token, "products")
    categories = goodtill_fetch_all(token, "categories")
    outlets = goodtill_fetch_all(token, "outlets")

    outlet_filter = env("GOODTILL_OUTLET_ID")
    cat_by_id = {c["id"]: c for c in categories}

    print("\nGoodtill outlets:")
    for o in outlets:
        mark = " <-- filter" if outlet_filter and o["id"] == outlet_filter else ""
        print(f"  - {o.get('outlet_name')} ({o.get('store_tag')}){mark}")

    # Active top-level sellable products
    candidates = []
    for p in products:
        if not p.get("active"):
            continue
        if not p.get("top_level_product"):
            continue
        if is_fee_or_system(p.get("product_name", "")):
            continue
        # When filtering by outlet: include shareable products + this outlet's products
        if outlet_filter:
            if not p.get("shareable") and p.get("outlet_id") != outlet_filter:
                continue
        price = float(p.get("selling_price") or 0)
        if price <= 0 and not p.get("is_open_price_product"):
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
        for p in candidates[:10]:
            cid = p.get("category_id")
            cname = (cat_by_id.get(cid) or {}).get("name", "?")
            img = "yes" if p.get("image") else "no"
            print(
                f"  {p.get('product_name')[:40]:40} £{p.get('selling_price'):>6}  [{cname}]  img={img}"
            )
        print("\nPreview complete. Run with --sync or --sync-images to import.")
        return 0

    if args.sync_images and not args.sync:
        return sync_images_only(token, candidates, args)

    print("\nConnecting to Odoo...")
    db, uid, password, models = odoo_connect()
    print(f"  Authenticated uid={uid}")

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
        cname = (cat_by_id.get(cid) or {}).get("name", "MISC")

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
        vals = {
            "name": name,
            "list_price": price,
            "default_code": default_code,
            "available_in_pos": True,
            "sale_ok": True,
            "type": "consu",
            "description_sale": desc,
            "pos_categ_ids": [(6, 0, [pos_categ_id])],
        }

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
