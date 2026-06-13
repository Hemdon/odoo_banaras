import logging

from odoo import api, SUPERUSER_ID


_logger = logging.getLogger(__name__)


PAAN_POS_CATEGORIES = {"PAAN", "ICE PAAN"}

EXCLUDED_NAME_PREFIXES = (
    "buy ",
    "free ",
    "hatch end - free ",
)


def _translated_name(record):
    value = record.with_context(lang="en_GB").name
    return (value or "").strip()


def post_init_hook(env):
    """Map existing POS Paan categories to eCommerce categories.

    Publication is deliberately limited to matched, saleable products. Existing
    products outside the Paan hierarchy are not modified, which keeps this hook
    safe for databases that host more than one website.
    """
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})

    pos_categories = env["pos.category"].search([])
    matched_products = env["product.template"]
    public_category = env.ref("theme_banaras_paan.public_category_paan")

    for pos_category in pos_categories:
        if _translated_name(pos_category).upper() not in PAAN_POS_CATEGORIES:
            continue

        products = env["product.template"].search(
            [("pos_categ_ids", "in", pos_category.id)]
        ).filtered(
            lambda product: product.active
            and product.sale_ok
            and product.list_price > 0
            and not _translated_name(product).lower().startswith(
                EXCLUDED_NAME_PREFIXES
            )
        )
        if products:
            products.write(
                {
                    "public_categ_ids": [(4, public_category.id)],
                    "is_published": True,
                }
            )
            matched_products |= products

    _logger.info(
        "Banaras Paan storefront prepared %s products for eCommerce",
        len(matched_products),
    )
