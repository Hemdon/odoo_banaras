/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    getClaimableRewards(couponId = false, programId = false, auto = false) {
        const rewards = super.getClaimableRewards(couponId, programId, auto);
        if (!auto) {
            return rewards;
        }
        return rewards.filter(
            ({ reward }) => reward.program_id?.program_type !== "loyalty"
        );
    },
});
