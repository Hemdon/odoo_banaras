#!/usr/bin/env python3
"""Tag premium-paan (and other) promo groups so POS Reward works for mixed products."""

GT_PREFIX = "GT-PROMO:"


def tag_for_program(prog) -> "env['product.tag']":
    Tag = env["product.tag"]
    slug = (prog.name or "").replace(GT_PREFIX, "")[:36]
    name = f"GT-Promo-{slug}"
    tag = Tag.search([("name", "=", name)], limit=1)
    if not tag:
        tag = Tag.create({"name": name})
    return tag


def run(env) -> None:
    programs = env["loyalty.program"].search(
        [("name", "=like", f"{GT_PREFIX}%"), ("program_type", "=", "buy_x_get_y")]
    )
    for prog in programs:
        tag = tag_for_program(prog)
        templates = prog.rule_ids.product_ids.product_tmpl_id
        if templates:
            templates.write({"product_tag_ids": [(4, tag.id)]})
        rule = prog.rule_ids[:1]
        reward = prog.reward_ids[:1]
        if rule:
            rule.write({"product_tag_id": tag.id, "product_ids": [(5, 0, 0)]})
        if reward:
            reward.write(
                {
                    "reward_product_tag_id": tag.id,
                    "reward_product_id": False,
                }
            )
        prog.write({"trigger": "auto", "applies_on": "current"})
    env.cr.commit()
    print(f"Tagged {len(programs)} buy_x_get_y programs. Close POS and open a new session.")


if "env" in dir():
    run(env)
