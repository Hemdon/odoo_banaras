/** @odoo-module **/

// PROOF OF CONCEPT — Royal Paan "Buy 3 Get 1 FREE" on the SELF-ORDER app.
// Self-order has no loyalty engine, so we compute the free item ourselves and add
// a clean £0 line (every 3 paid Royal paan => 1 free). Detects Royal paan by its
// product tag (id 1). Recomputes whenever the cart changes.

import { patch } from "@web/core/utils/patch";
import { SelfOrder } from "@pos_self_order/app/services/self_order_service";
import { CartPage } from "@pos_self_order/app/pages/cart_page/cart_page";
import { getOrderLineValues } from "@pos_self_order/app/services/card_utils";

const ROYAL_TAG_ID = 1; // product.tag identifying Royal Paan (used if tags are loaded)
const ROYAL_BUY = 3;
const ROYAL_FREE = 1;
const FREE_NOTE = "Buy 3 Get 1 FREE - Banaras Royal Paan";

// Same list the (working) self-order paan grouping uses — name match is reliable
// in self-order, where the product tag relation may not be loaded on order lines.
// All 9 products carrying the Royal Paan tag (matches the till's tag-based offer).
const ROYAL_NAMES = new Set(
    [
        "Special Mystic Banaras",
        "Bombay Imperial Paan",
        "Kalkatti Rajwadi Supari",
        "Pushpa Sandalwood Paan",
        "Rose Royal Paan",
        "Royal DARK Chocolate",
        "Royal MILK Chocolate",
        "Royal ORANGE Chocolate",
        "Royal WHITE Chocolate",
    ].map((n) => n.toLowerCase())
);

function localizedText(value) {
    if (!value || typeof value !== "object") {
        return value || "";
    }
    return value.en_GB || value.en_US || Object.values(value).find(Boolean) || "";
}

function productTags(product) {
    const tmpl = product?.product_tmpl_id;
    const tags =
        (tmpl?.product_tag_ids && tmpl.product_tag_ids.length
            ? tmpl.product_tag_ids
            : product?.product_tag_ids) || [];
    return tags.map((t) => t.id);
}

function lineProductName(line) {
    const p = line.product_id;
    return localizedText(p?.name || p?.product_tmpl_id?.name || p?.display_name)
        .trim()
        .toLowerCase();
}

function isPaidRoyal(line) {
    if (line.uiState?.banarasFreeRoyal) {
        return false;
    }
    return ROYAL_NAMES.has(lineProductName(line)) || productTags(line.product_id).includes(ROYAL_TAG_ID);
}

function applyRoyalOffer(selfOrder) {
    const order = selfOrder?.currentOrder;
    if (!order || !order.lines) {
        return;
    }
    const royalLines = order.lines.filter(isPaidRoyal);
    const paidQty = royalLines.reduce((sum, line) => sum + (line.qty || 0), 0);
    const freeQty = Math.floor(paidQty / ROYAL_BUY) * ROYAL_FREE;

    let freeLine = order.lines.find((line) => line.uiState?.banarasFreeRoyal);

    if (freeQty <= 0) {
        if (freeLine) {
            freeLine.delete();
        }
        return;
    }

    // The free unit is the cheapest qualifying Royal paan in the cart.
    const cheapest = royalLines
        .slice()
        .sort((a, b) => (a.price_unit || 0) - (b.price_unit || 0))[0];
    const tmpl = cheapest?.product_id?.product_tmpl_id;
    if (!tmpl) {
        if (freeLine) {
            freeLine.delete();
        }
        return;
    }

    if (freeLine) {
        if (freeLine.qty !== freeQty) {
            freeLine.setQuantity(freeQty);
        }
        freeLine.price_unit = 0;
        return;
    }

    const values = getOrderLineValues(selfOrder, tmpl, freeQty, FREE_NOTE);
    values.price_unit = 0;
    values.price_extra = 0;
    const line = selfOrder.models["pos.order.line"].create(values);
    line.uiState = { ...(line.uiState || {}), banarasFreeRoyal: true };
    line.price_unit = 0;
}

patch(SelfOrder.prototype, {
    async addToCart() {
        const result = await super.addToCart(...arguments);
        try {
            applyRoyalOffer(this);
        } catch (e) {
            console.error("Banaras royal self-order offer failed:", e);
        }
        return result;
    },
});

patch(CartPage.prototype, {
    changeQuantity(line) {
        const result = super.changeQuantity(...arguments);
        try {
            applyRoyalOffer(this.selfOrder);
        } catch (e) {
            console.error("Banaras royal self-order offer failed:", e);
        }
        return result;
    },
});
