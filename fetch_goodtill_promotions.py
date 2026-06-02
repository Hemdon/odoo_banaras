#!/usr/bin/env python3
"""Export Goodtill promotions (external API) and coupons to JSON for Odoo loyalty sync."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date
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


def login() -> str:
    load_dotenv(Path(__file__).parent / ".env")
    return json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                "https://api.thegoodtill.com/api/login",
                data=json.dumps(
                    {
                        "subdomain": os.environ["GOODTILL_SUBDOMAIN"],
                        "username": os.environ["GOODTILL_USERNAME"],
                        "password": os.environ["GOODTILL_PASSWORD"],
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        ).read()
    )["token"]


def main() -> None:
    token = login()
    h = {"Authorization": f"Bearer {token}"}

    legacy = json.loads(
        urllib.request.urlopen(
            urllib.request.Request("https://api.thegoodtill.com/api/promotions", headers=h)
        ).read()
    )["data"]

    external = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                "https://api.thegoodtill.com/api/external/promotions", headers=h
            )
        ).read()
    )["data"]["promotions"]

    coupons_raw = json.loads(
        urllib.request.urlopen(
            urllib.request.Request("https://api.thegoodtill.com/api/coupons", headers=h)
        ).read()
    )["data"]["coupons"]

    today = date.today().isoformat()
    live_external = [
        p
        for p in external
        if p.get("active")
        and p.get("supports_pos")
        and (p.get("end_datetime") or "9999")[:10] >= today
        and (p.get("products") or [])
    ]

    out = {
        "exported_at": today,
        "legacy_promotions": legacy,
        "external_promotions": external,
        "live_external_promotions": live_external,
        "coupons": coupons_raw,
        "live_coupons": [
            c
            for c in coupons_raw
            if c.get("active")
            and c.get("supports_pos")
            and (c.get("expires_at") or "9999") >= today
        ],
    }

    path = Path(__file__).parent / "goodtill_promotions.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {path}")
    print(f"  external promotions: {len(external)}")
    print(f"  live POS product promos: {len(live_external)}")
    print(f"  legacy button promos: {len(legacy)}")
    print(f"  live POS coupons: {len(out['live_coupons'])}")


if __name__ == "__main__":
    main()
