import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Royal Paan "Buy 3 Get 1 FREE" applied to SELF-ORDER orders server-side, since the
# self-order frontend has no loyalty engine. Idempotent + scoped, so till orders
# (which already get the reward client-side) are never doubled.
ROYAL_TAG_ID = 1                 # product.tag identifying Royal Paan products
ROYAL_DISCOUNT_PRODUCT_ID = 822  # Hounslow Royal reward discount line product (program 30)
HOUNSLOW_CONFIG_ID = 18


def _royal_free_qty(royal_units):
    # Mirrors the till's computeFirstThresholdRewardQty(qty, 3, 1) = floor((qty+1)/4).
    return max(0, (royal_units + 1) // 4)


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _banaras_apply_self_royal_offer(self):
        for order in self:
            try:
                if order.config_id.id != HOUNSLOW_CONFIG_ID:
                    continue
                royal_lines = order.lines.filtered(
                    lambda l: not l.is_reward_line
                    and l.product_id
                    and ROYAL_TAG_ID in l.product_id.product_tmpl_id.product_tag_ids.ids
                )
                royal_units = int(sum(royal_lines.mapped("qty")))
                if royal_units <= 0:
                    continue

                desired_free = _royal_free_qty(royal_units)
                discount_lines = order.lines.filtered(
                    lambda l: l.product_id.id == ROYAL_DISCOUNT_PRODUCT_ID
                )
                existing_free = int(sum(abs(q) for q in discount_lines.mapped("qty")))
                to_add = desired_free - existing_free
                if to_add <= 0:
                    continue  # till already applied it (or nothing to add)

                unit_prices = [p for p in royal_lines.mapped("price_unit") if p > 0]
                if not unit_prices:
                    continue
                cheapest = min(unit_prices)

                self.env["pos.order.line"].create({
                    "order_id": order.id,
                    "product_id": ROYAL_DISCOUNT_PRODUCT_ID,
                    "qty": to_add,
                    "price_unit": -cheapest,
                    "price_subtotal": -cheapest * to_add,
                    "price_subtotal_incl": -cheapest * to_add,
                    "full_product_name": "Buy 3 Get 1 FREE - Banaras Royal Paan",
                    "tax_ids": [(6, 0, [])],
                })
            except Exception:
                _logger.exception(
                    "Banaras self-order royal offer failed for order %s", order.id
                )

    def _process_order(self, order, existing_order):
        order_id = super()._process_order(order, existing_order)
        try:
            self.browse(order_id)._banaras_apply_self_royal_offer()
        except Exception:
            _logger.exception("Banaras royal offer post-process hook failed")
        return order_id
