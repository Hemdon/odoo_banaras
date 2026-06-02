#!/usr/bin/env python3
"""Export Goodtill print/KDS flags per product to JSON for setup_goodtill_print_routing.py."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def main() -> None:
    load_dotenv(Path(__file__).parent / ".env")
    sub = os.environ["GOODTILL_SUBDOMAIN"]
    user = os.environ["GOODTILL_USERNAME"]
    pw = os.environ["GOODTILL_PASSWORD"]
    outlet = os.environ.get(
        "GOODTILL_OUTLET_ID", "02f13246-56ff-404e-84b8-ad3200601295"
    )

    tok = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                "https://api.thegoodtill.com/api/login",
                data=json.dumps(
                    {"subdomain": sub, "username": user, "password": pw}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        ).read()
    )["token"]

    h = {"Authorization": f"Bearer {tok}", "Outlet-Id": outlet}
    prods = json.loads(
        urllib.request.urlopen(
            urllib.request.Request("https://api.thegoodtill.com/api/products", headers=h)
        ).read()
    )["data"]

    out = []
    for p in prods:
        if not p.get("active"):
            continue
        out.append(
            {
                "id": p["id"],
                "name": (p.get("product_name") or "").strip(),
                "sku": (p.get("product_sku") or "").strip(),
                "parent_id": p.get("parent_product_id"),
                "print_on_receipt": bool(p.get("print_on_receipt")),
                "print_on_kitchen": bool(p.get("print_on_kitchen")),
                "print_on_drink": bool(p.get("print_on_drink")),
                "print_on_other": bool(p.get("print_on_other")),
            }
        )

    path = Path(__file__).parent / "goodtill_print_flags.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {len(out)} products to {path}")


if __name__ == "__main__":
    main()
