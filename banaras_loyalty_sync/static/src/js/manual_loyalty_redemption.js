/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    // Loyalty POINT rewards (program_type "loyalty") must only ever be redeemed
    // MANUALLY by staff via the Rewards button — never auto-applied when a customer
    // is selected. Buy-X-Get-Y promotions are NOT loyalty type, so they still
    // auto-apply as normal.
    _banarasProgramType(reward) {
        // Resolve the program robustly: reward.program_id may be a record OR a bare id.
        if (reward?.program_id?.program_type) {
            return reward.program_id.program_type;
        }
        const id = reward?.program_id?.id ?? reward?.program_id;
        return this.models?.["loyalty.program"]?.get?.(id)?.program_type;
    },

    getClaimableRewards(couponId = false, programId = false, auto = false) {
        const rewards = super.getClaimableRewards(couponId, programId, auto);
        if (!auto) {
            return rewards;
        }
        return rewards.filter(({ reward }) => this._banarasProgramType(reward) !== "loyalty");
    },
});
