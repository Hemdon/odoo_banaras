#!/usr/bin/env python3
"""
Map Goodtill print / KDS flags to Odoo POS preparation printers (both branches).

Goodtill flags → Odoo routing POS categories (hidden from till grid):
  print_on_receipt  → customer receipt (default POS behaviour)
  print_on_kitchen  → category "Send to Kitchen" → kitchen preparation printer
  print_on_drink    → category "Send to Drinks"   → drinks preparation printer
  print_on_other    → category "Send to Other"    → other preparation printer

Requires goodtill_print_flags.json (run fetch_goodtill_print_flags.py first).

Server:
  sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d Main_Banaras --no-http \\
    < setup_goodtill_print_routing.py
"""

from __future__ import annotations

import json
from pathlib import Path

GT_REF = "GT:"
ROUTING_CATEGORIES = {
    "kitchen": "Send to Kitchen",
    "drinks": "Send to Drinks",
    "other": "Send to Other",
}
PRINTERS = {
    "kitchen": "Kitchen Printer",
    "drinks": "Drinks Printer",
    "other": "Other Printer",
}
POS_CONFIG_IDS = (9, 13)  # Main Register, Hatch End Register
COMPANY_ID = 4  # Banaras Paan (shared products)
FLAGS_JSON = Path(__file__).resolve().parent / "goodtill_print_flags.json"


def load_gt_flags() -> list[dict]:
    if not FLAGS_JSON.exists():
        raise SystemExit(
            f"Missing {FLAGS_JSON.name}. Run: python3 fetch_goodtill_print_flags.py"
        )
    return json.loads(FLAGS_JSON.read_text())


def run(env) -> None:
    PT = env["product.template"]
    PosCat = env["pos.category"]
    Printer = env["pos.printer"]
    PosConfig = env["pos.config"]

    gt_products = load_gt_flags()
    # Merge flags onto parent GT ids (variants inherit parent routing)
    by_id = {p["id"]: p for p in gt_products}
    effective: dict[str, dict] = {}

    def merge_flags(pid: str) -> dict:
        p = by_id.get(pid)
        if not p:
            return {}
        flags = {
            "receipt": p["print_on_receipt"],
            "kitchen": p["print_on_kitchen"],
            "drinks": p["print_on_drink"],
            "other": p["print_on_other"],
            "name": p["name"],
            "sku": p["sku"],
        }
        parent = p.get("parent_id")
        if parent and parent in by_id:
            pf = merge_flags(parent)
            for k in ("receipt", "kitchen", "drinks", "other"):
                flags[k] = flags[k] or pf.get(k, False)
        return flags

    for p in gt_products:
        effective[p["id"]] = merge_flags(p["id"])

    # Routing categories (not added to POS floor)
    route_cat_ids: dict[str, int] = {}
    for key, cname in ROUTING_CATEGORIES.items():
        cat = PosCat.search([("name", "=", cname)], limit=1)
        if not cat:
            cat = PosCat.create({"name": cname, "sequence": 900 + len(route_cat_ids)})
        route_cat_ids[key] = cat.id
        print(f"Category: {cname} (id={cat.id})")

    # Preparation printers
    printer_records = {}
    for key, pname in PRINTERS.items():
        pr = Printer.search([("name", "=", pname)], limit=1)
        vals = {
            "name": pname,
            "printer_type": "epson_epos",
            "epson_printer_ip": "0.0.0.0",
            "company_id": COMPANY_ID,
            "product_categories_ids": [(6, 0, [route_cat_ids[key]])],
        }
        if pr:
            pr.write(vals)
        else:
            pr = Printer.create(vals)
        printer_records[key] = pr
        print(f"Printer: {pname} (id={pr.id})")

    all_printer_ids = [p.id for p in printer_records.values()]
    for pos_id in POS_CONFIG_IDS:
        pos = PosConfig.browse(pos_id)
        pos.write(
            {
                "is_order_printer": True,
                "printer_ids": [(6, 0, all_printer_ids)],
            }
        )
        print(f"POS {pos.name}: preparation printers enabled ({len(all_printer_ids)})")

    def find_template(gt_row: dict):
        ref = f"{GT_REF}{gt_row['id']}"
        t = PT.search([("default_code", "=", ref)], limit=1)
        if t:
            return t
        if gt_row.get("sku"):
            t = PT.search([("default_code", "=", gt_row["sku"])], limit=1)
            if t:
                return t
        name = gt_row.get("name") or ""
        if name:
            t = PT.search([("name", "=", name)], limit=1)
            if t:
                return t
        return PT.browse()

    from collections import defaultdict

    template_flags: dict[int, dict] = defaultdict(
        lambda: {"kitchen": False, "drinks": False, "other": False}
    )
    missing = 0

    for gid, flags in effective.items():
        row = by_id[gid]
        tmpl = find_template(row)
        if not tmpl and row.get("parent_id") and row["parent_id"] in by_id:
            tmpl = find_template(by_id[row["parent_id"]])
        if not tmpl:
            missing += 1
            continue
        tf = template_flags[tmpl.id]
        tf["kitchen"] |= bool(flags.get("kitchen"))
        tf["drinks"] |= bool(flags.get("drinks"))
        tf["other"] |= bool(flags.get("other"))

    updated = 0
    route_ids_set = set(route_cat_ids.values())
    for tmpl_id, flags in template_flags.items():
        tmpl = PT.browse(tmpl_id)
        keep = [c.id for c in tmpl.pos_categ_ids if c.id not in route_ids_set]
        extra = []
        if flags["kitchen"]:
            extra.append(route_cat_ids["kitchen"])
        if flags["drinks"]:
            extra.append(route_cat_ids["drinks"])
        if flags["other"]:
            extra.append(route_cat_ids["other"])
        tmpl.write({"pos_categ_ids": [(6, 0, list(dict.fromkeys(keep + extra)))]})
        updated += 1

    env.cr.commit()
    print(f"\nUpdated {updated} products with Goodtill print routing.")
    print(f"No Odoo match for {missing} Goodtill rows (variants/skus may duplicate).")
    print(
        "\nNext steps:"
        "\n  1. Point of Sale → Configuration → Preparation Printers"
        "\n     Set real Epson IP for Kitchen / Drinks / Other printers."
        "\n  2. Close and reopen POS sessions on both registers."
        "\n  3. KDS screen: install Odoo 'Preparation Display' app if available (Enterprise)."
        "\n     Until then, kitchen/drinks tickets use preparation printers on Order."
    )


if "env" in dir():
    run(env)
