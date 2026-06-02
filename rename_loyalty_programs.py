#!/usr/bin/env python3
"""Rename GT-PROMO:{uuid} loyalty programs to Goodtill promotion names."""

from __future__ import annotations

import json
from pathlib import Path

from setup_goodtill_promotions import (
    GT_PREFIX,
    display_name_from_promo,
    program_ref,
)

FLAGS_JSON = Path(__file__).resolve().parent / "goodtill_promotions.json"

LEGACY_NAMES = {
    "HP": "Half Price",
    "BOGOF": "Buy one get one FREE",
}


def run(env) -> None:
    if not FLAGS_JSON.exists():
        raise SystemExit("Run fetch_goodtill_promotions.py first.")
    data = json.loads(FLAGS_JSON.read_text())
    Program = env["loyalty.program"]
    renamed = 0

    for promo in data.get("external_promotions", []):
        gt_id = promo.get("id")
        if not gt_id:
            continue
        new_name = display_name_from_promo(promo)
        prog = Program.search([("name", "=", program_ref(gt_id))], limit=1)
        if prog and prog.name != new_name:
            prog.write({"name": new_name})
            renamed += 1
            print(f"  {new_name}")

    for p in data.get("legacy_promotions", []):
        code = (p.get("promo_code") or "").strip().upper()
        if not code:
            continue
        new_name = LEGACY_NAMES.get(code) or (p.get("promo_name") or code)
        prog = Program.search([("name", "=", program_ref(code))], limit=1)
        if prog and prog.name != new_name:
            prog.write({"name": new_name})
            renamed += 1
            print(f"  {new_name}")

    for coupon in data.get("coupons", []):
        code = (coupon.get("coupon_code") or "").strip().upper()
        if not code:
            continue
        prog = Program.search([("name", "=", program_ref(code))], limit=1)
        if not prog:
            prog = Program.search([("name", "=", f"Goodtill {code}")], limit=1)
        if prog and prog.name != code:
            prog.write({"name": code})
            renamed += 1
            print(f"  {code}")

    test = Program.search([("name", "=", "GT-PROMO:TEST-B5G1-HE")], limit=1)
    if test:
        test.write({"active": False})

    env.cr.commit()
    print(f"\nRenamed {renamed} programs. Close POS and start a new session.")


if "env" in dir():
    run(env)
