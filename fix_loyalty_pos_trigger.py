#!/usr/bin/env python3
"""One-off fix: loyalty programs need trigger=auto for POS Reward button. Run via odoo shell."""

GT_PREFIX = "GT-PROMO:"


def run(env) -> None:
    programs = env["loyalty.program"].search([("name", "=like", f"{GT_PREFIX}%")])
    for prog in programs:
        if prog.program_type in ("buy_x_get_y", "promotion"):
            prog.write({"trigger": "auto", "applies_on": "current"})
            prog.rule_ids.write({"mode": "auto"})
        elif prog.program_type == "promo_code":
            prog.write({"trigger": "with_code"})
        if prog.program_type == "buy_x_get_y" and prog.rule_ids and prog.reward_ids:
            vids = prog.rule_ids[0].product_ids.ids
            if vids:
                prog.reward_ids[0].write(
                    {
                        "multi_product": True,
                        "reward_product_ids": [(6, 0, vids)],
                        "reward_product_id": vids[0],
                    }
                )
    test = env["loyalty.program"].search([("name", "=", "GT-PROMO:TEST-B5G1-HE")])
    if test:
        test.write({"active": False})
    env.cr.commit()
    print(f"Fixed {len(programs)} programs. Close POS session and open a new one.")


if "env" in dir():
    run(env)
