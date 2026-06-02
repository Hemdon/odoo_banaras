#!/usr/bin/env python3
"""Refresh points_per_currency from Goodtill; keep category/product lists in goodtill_loyalty.json."""

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


def main() -> None:
    load_dotenv(Path(__file__).parent / ".env")
    tok = json.loads(
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
    settings = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                "https://api.thegoodtill.com/api/loyalty/settings",
                headers={"Authorization": f"Bearer {tok}"},
            )
        ).read()
    )
    points_per = int(settings.get("data", {}).get("points_per_currency") or 5)

    path = Path(__file__).parent / "goodtill_loyalty.json"
    if path.exists():
        cfg = json.loads(path.read_text())
        cfg["points_per_currency"] = points_per
        cfg["exported_at"] = date.today().isoformat()
        path.write_text(json.dumps(cfg, indent=2))
        print(f"Updated {path} points_per_currency={points_per}")
    else:
        print("goodtill_loyalty.json not found — use repo template")


if __name__ == "__main__":
    main()
