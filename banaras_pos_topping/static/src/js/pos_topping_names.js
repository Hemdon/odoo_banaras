/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import * as posUtils from "@point_of_sale/utils";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

function toppingBaseName(line) {
    return line?.product_id?.description_sale || line?.product_id?.name || "";
}

function comboGroupName(line) {
    return line?.combo_item_id?.combo_id?.name || "";
}

function formatToppingLabel(line, { receipt = false } = {}) {
    const attributeString = posUtils.constructAttributeString(line);
    let base = toppingBaseName(line);
    if (attributeString) {
        base = `${base} (${attributeString})`;
    }
    const group = comboGroupName(line);
    if (group) {
        return receipt ? `${group}: ${base}` : `${group}: ${line?.product_id?.name || base}`;
    }
    return base;
}

patch(posUtils, {
    constructFullProductName(line) {
        return formatToppingLabel(line, { receipt: true });
    },
});

patch(PosOrderline.prototype, {
    setFullProductName() {
        this.full_product_name = posUtils.constructFullProductName(this);
    },

    get orderDisplayProductName() {
        const group = comboGroupName(this);
        if (group) {
            return {
                name: `${group}: ${this.product_id?.name || ""}`,
                attributeString: posUtils.constructAttributeString(this),
            };
        }
        return {
            name: this.product_id?.name,
            attributeString: posUtils.constructAttributeString(this),
        };
    },
});
