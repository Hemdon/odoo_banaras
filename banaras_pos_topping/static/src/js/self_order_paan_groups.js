/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductListPage } from "@pos_self_order/app/pages/product_list_page/product_list_page";

const PAAN_CATEGORY_ID = 21;
const PAAN_GROUPS = [
    {
        title: "ROYAL PAAN",
        names: [
            "Special Mystic Banaras",
            "Bombay Imperial Paan",
            "Kalkatti Rajwadi Supari",
            "Pushpa Sandalwood Paan",
            "Rose Royal Paan",
        ],
    },
    {
        title: "PREMIUM PAAN",
        names: [
            "Bombay Magai Paan",
            "Raat Rani Paan(Night Queen Paan)",
            "Raat Rani / Night Queen Paan",
            "Special Banaras Paan",
            "Navratna Paan",
            "Banaras King Paan",
            "Bombay Bad Boy",
        ],
    },
    {
        title: "DELUXE PAAN",
        names: [
            "Elaichi Paan",
            "Mughdha Ras Paan",
            "Mughdha Raas Paan",
            "Kalkatti Supari Paan",
            "Banaras Coconut Paan",
        ],
    },
    {
        title: "STANDARD SWEET PAAN",
        names: ["Saffron Sweet Paan", "Pineapple Flavour Paan", "Rose Paan", "Sada Khara Paan"],
    },
    {
        title: "BANARAS ICE PAAN",
        names: [
            "Royal MILK Chocolate",
            "Royal DARK Chocolate",
            "Royal ORANGE Chocolate",
            "Royal WHITE Chocolate",
            "Banaras Rajwari ICE",
            "Pushpa Sandalwood ICE Paan",
        ],
    },
    { title: "OTHER Products", names: ["Fire Paan"] },
];

function localizedText(value) {
    if (!value || typeof value !== "object") {
        return value || "";
    }
    return value.en_GB || value.en_US || Object.values(value).find(Boolean) || "";
}

function productName(product) {
    return localizedText(product?.name || product?.display_name);
}

function groupedPaanProducts(products) {
    const remaining = [...products];
    const groups = [];
    for (const group of PAAN_GROUPS) {
        const wanted = new Set(group.names);
        const groupProducts = [];
        for (const product of [...remaining]) {
            if (wanted.has(productName(product))) {
                groupProducts.push(product);
                remaining.splice(remaining.indexOf(product), 1);
            }
        }
        if (groupProducts.length) {
            groups.push([group.title, groupProducts]);
        }
    }
    if (remaining.length) {
        groups.push(["OTHER Products", remaining]);
    }
    return groups;
}

patch(ProductListPage.prototype, {
    setup() {
        super.setup(...arguments);
        const paanCategory = this.state.topCategories.find((category) => category.id === PAAN_CATEGORY_ID);
        if (paanCategory && !this.selfOrder.currentCategory) {
            this.state.selectedCategory = paanCategory;
        }
    },

    getBanarasPaanProductGroups(category, productList) {
        if (category?.id !== PAAN_CATEGORY_ID) {
            return [[false, productList]];
        }
        return groupedPaanProducts(productList);
    },
});
