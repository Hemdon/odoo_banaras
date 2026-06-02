#!/usr/bin/env python3
"""Update POC topping labels (short POS name, full receipt) and combo qty limits."""

from __future__ import annotations

TOPPING_QTY_MAX = 10  # per group (Popping Boba / Pearls & Jelly)

POPPING = [
    "Apple Popping",
    "Blueberry Popping",
    "Cherry Popping",
    "Lychee Popping",
    "Mango Popping",
    "Passion Popping",
    "Peach Popping",
    "Raspberry Popping",
    "Strawberry Popping",
    "Chocolate Popping",
    "Pineapple Popping",
    "Kiwi Fruit Popping",
    "Lemon Popping",
    "HoneyDew Popping",
]

JELLY = [
    "Topioca Pearl",
    "Mango Jelly",
    "Coconut Jelly",
    "Lychee Coconut Jelly",
    "PINEAPPLE Jelly",
    "STRAWBERRY Jelly",
]


def pos_short_name(receipt_name: str) -> str:
    n = receipt_name.strip()
    for suffix in (" Popping", " Jelly"):
        if n.endswith(suffix):
            return n[: -len(suffix)]
    return n


def update_topping(env, receipt_name: str) -> None:
    PT = env["product.template"]
    code = "TOP:" + receipt_name.upper().replace(" ", "_")[:40]
    tmpl = PT.search([("default_code", "=", code)], limit=1)
    if not tmpl:
        tmpl = PT.search([("name", "=", receipt_name)], limit=1)
    if not tmpl:
        print("  skip (not found):", receipt_name)
        return
    short = pos_short_name(receipt_name)
    tmpl.write(
        {
            "name": short,
            "description_sale": receipt_name,
            "default_code": code,
        }
    )
    print(f"  {short!r} → receipt {receipt_name!r}")


def run(env) -> None:
    Combo = env["product.combo"]
    for combo_name, names in [("Popping Boba", POPPING), ("Pearls & Jelly", JELLY)]:
        combo = Combo.search([("name", "=", combo_name)], limit=1)
        if combo:
            combo.write({"qty_max": TOPPING_QTY_MAX, "qty_free": 0})
            print(f"{combo_name}: qty_max={TOPPING_QTY_MAX}")
        for n in names:
            update_topping(env, n)
    env.cr.commit()
    print("Done. Close POS session and reopen.")


if "env" in dir():
    run(env)
