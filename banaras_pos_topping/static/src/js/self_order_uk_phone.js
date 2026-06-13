/** @odoo-module **/

import { PresetInfoPopup } from "@pos_self_order/app/components/preset_info_popup/preset_info_popup";
import { isValidPhone } from "@point_of_sale/utils";
import { patch } from "@web/core/utils/patch";

function normalizeUKPhone(value) {
    const phone = String(value || "").trim().replace(/[\s.\-()]/g, "");
    if (phone.startsWith("0044")) {
        return `+44${phone.slice(4)}`;
    }
    if (phone.startsWith("0")) {
        return `+44${phone.slice(1)}`;
    }
    return phone;
}

patch(PresetInfoPopup.prototype, {
    normalizePhone() {
        this.state.phone = normalizeUKPhone(this.state.phone);
    },

    checkPhoneFormat() {
        const phone = normalizeUKPhone(this.state.phone);
        return !phone || isValidPhone(phone);
    },

    get validSelection() {
        return this.selfOrder.isValidSelection(this.state.selectedSlot, {
            id: parseInt(this.state.selectedPartnerId),
            name: this.state.name,
            email: this.state.email,
            phone: normalizeUKPhone(this.state.phone),
            street: this.state.street,
            city: this.state.city,
            country_id: this.state.countryId,
            state_id: this.state.stateId,
            zip: this.state.zip,
        });
    },

    async setInformations() {
        this.normalizePhone();
        return super.setInformations(...arguments);
    },
});
