/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import * as posUtils from "@point_of_sale/utils";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";

function hideRestaurantTablesButton() {
    document.querySelectorAll("button.table-button, .table-button").forEach((button) => button.remove());
}

function watchRestaurantTablesButton() {
    if (typeof document === "undefined") {
        return;
    }
    const start = () => {
        hideRestaurantTablesButton();
        if (typeof MutationObserver !== "undefined" && document.body) {
            new MutationObserver(hideRestaurantTablesButton).observe(document.body, {
                childList: true,
                subtree: true,
            });
        }
    };
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
}

watchRestaurantTablesButton();

// Offer programs are auto-detected by NAME from the loaded loyalty.program records
// (see rebuildBanarasProgramMaps) so every branch — including ones added later —
// works without editing this file, as long as the naming convention is kept:
//   "Buy 3 Get 1 FREE - Banaras Royal Paan (<Branch>)"
//   "Buy 8 Get 2 FREE - Banaras Premium Paan (<Branch>)"
//   "Buy 5 Get 1 FREE - Banaras Premium Paan (<Branch>)"
//   "Buy 3 Get 1 FREE - Bubble Tea"
// The KNOWN_* ids are a safety net for the existing branches (Hatch End / Rayners /
// Hounslow) so offers never break even if name detection ever misses.
const KNOWN_ROYAL_PROGRAM_IDS = [10, 25, 30];
const KNOWN_TIER_PAIRS = [[11, 12], [13, 14], [28, 29]]; // [Premium 8/2, Premium 5/1]
const KNOWN_BUBBLE_PROGRAM_IDS = [15];
const BUBBLE_TEA_REWARD_LABEL = "Buy 3 Get 1 FREE - Bubble Tea";

let BANARAS_TIER_RULES = [];
let BUBBLE_TEA_PROGRAM_ID = KNOWN_BUBBLE_PROGRAM_IDS[0];
let ROYAL_PAAN_PROGRAM_IDS = [...KNOWN_ROYAL_PROGRAM_IDS];
let BANARAS_AUTO_PRODUCT_PROGRAM_IDS = new Set();

function parseBuyGet(name) {
    const m = /Buy\s+(\d+)\s+Get\s+(\d+)/i.exec(name || "");
    return m ? { buy: Number(m[1]), free: Number(m[2]) } : null;
}

function loadedLoyaltyPrograms(models) {
    const coll = models?.["loyalty.program"];
    if (!coll) {
        return [];
    }
    if (typeof coll.getAll === "function") {
        return coll.getAll();
    }
    return Array.isArray(coll.records) ? coll.records : [];
}

function rebuildBanarasProgramMaps(models) {
    const royal = new Set(KNOWN_ROYAL_PROGRAM_IDS);
    const bubble = new Set(KNOWN_BUBBLE_PROGRAM_IDS);
    const premiumByBranch = {};

    for (const program of loadedLoyaltyPrograms(models)) {
        if (program.program_type !== "buy_x_get_y") {
            continue;
        }
        const name = localizedText(program.name);
        if (/Royal\s+Paan/i.test(name)) {
            royal.add(program.id);
        } else if (/Premium\s+Paan/i.test(name)) {
            const bg = parseBuyGet(name);
            if (!bg) {
                continue;
            }
            const branch = (/\(([^)]+)\)\s*$/.exec(name) || [])[1] || name;
            premiumByBranch[branch] = premiumByBranch[branch] || {};
            if (bg.buy >= 8) {
                premiumByBranch[branch].better = { id: program.id, ...bg };
            } else {
                premiumByBranch[branch].lower = { id: program.id, ...bg };
            }
        } else if (/Bubble\s+Tea/i.test(name)) {
            bubble.add(program.id);
        }
    }

    const rules = [];
    const seen = new Set();
    const addTier = (b, l, bBuy = 8, bFree = 2, lBuy = 5, lFree = 1) => {
        const key = `${b}-${l}`;
        if (seen.has(key)) {
            return;
        }
        seen.add(key);
        rules.push({
            betterProgramId: b,
            lowerProgramId: l,
            betterBuy: bBuy,
            betterFree: bFree,
            lowerBuy: lBuy,
            lowerFree: lFree,
        });
    };
    for (const branch of Object.keys(premiumByBranch)) {
        const { better, lower } = premiumByBranch[branch];
        if (better && lower) {
            addTier(better.id, lower.id, better.buy, better.free, lower.buy, lower.free);
        }
    }
    for (const [b, l] of KNOWN_TIER_PAIRS) {
        addTier(b, l);
    }

    BANARAS_TIER_RULES = rules;
    ROYAL_PAAN_PROGRAM_IDS = [...royal];
    BUBBLE_TEA_PROGRAM_ID = [...bubble][0] ?? KNOWN_BUBBLE_PROGRAM_IDS[0];
    BANARAS_AUTO_PRODUCT_PROGRAM_IDS = new Set([
        ...bubble,
        ...royal,
        ...rules.flatMap((tier) => [tier.betterProgramId, tier.lowerProgramId]),
    ]);
}
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

function templateName(product) {
    return localizedText(product?.name || product?.display_name);
}

function groupPaanProducts(products) {
    const remaining = [...products];
    const groups = [];

    for (const group of PAAN_GROUPS) {
        const wanted = new Set(group.names);
        const groupProducts = [];
        for (const product of [...remaining]) {
            if (wanted.has(templateName(product))) {
                groupProducts.push(product);
                remaining.splice(remaining.indexOf(product), 1);
            }
        }
        if (groupProducts.length) {
            groups.push(["banaras-" + group.title, groupProducts, group.title]);
        }
    }

    if (remaining.length) {
        groups.push(["banaras-other-paan", remaining, "OTHER Products"]);
    }

    return groups;
}

function productName(line) {
    return localizedText(line?.product_id?.name || line?.product_id?.display_name);
}

function rewardLineDisplayName(line) {
    if (line?.reward_id?.program_id?.id === BUBBLE_TEA_PROGRAM_ID) {
        return BUBBLE_TEA_REWARD_LABEL;
    }
    return "";
}

function isGoodTillSyncDescription(description) {
    return String(description || "").startsWith("Synced from Goodtill.");
}

function toppingBaseName(line, { receipt = false } = {}) {
    const rewardName = rewardLineDisplayName(line);
    if (rewardName) {
        return rewardName;
    }
    const description = localizedText(line?.product_id?.description_sale);
    if (receipt && isGoodTillSyncDescription(description)) {
        return productName(line);
    }
    return description || productName(line);
}

function comboGroupName(line) {
    return line?.combo_item_id?.combo_id?.name || "";
}

function iceCreamOptionLabel(line) {
    const group = localizedText(comboGroupName(line));
    if (!group.endsWith(" Ice Cream Option")) {
        return "";
    }
    const name = productName(line);
    const match = name.match(
        /^(.*?)\s+(1\s+Litre|1\s+Scoop\s+Scoop|1\s+Scoop\s+Waffle\s+Cone|2\s+Scoops\s+Scoop|2\s+Scoops\s+Waffle\s+Cone)$/i
    );
    if (!match) {
        return name;
    }
    return match[2]
        .replace(/\s+/g, " ")
        .replace(/^1 Scoop Scoop$/i, "1 Scoop - Scoop")
        .replace(/^1 Scoop Waffle Cone$/i, "1 Scoop - Waffle Cone")
        .replace(/^2 Scoops Scoop$/i, "2 Scoops - Scoop")
        .replace(/^2 Scoops Waffle Cone$/i, "2 Scoops - Waffle Cone");
}

function formatToppingLabel(line, { receipt = false } = {}) {
    const iceCreamLabel = iceCreamOptionLabel(line);
    if (iceCreamLabel) {
        return iceCreamLabel;
    }
    const attributeString = posUtils.constructAttributeString(line);
    let base = toppingBaseName(line, { receipt });
    if (attributeString) {
        base = `${base} (${attributeString})`;
    }
    const group = comboGroupName(line);
    if (group) {
        return receipt ? `${group}: ${base}` : `${group}: ${productName(line) || base}`;
    }
    return base;
}

function computeBuyXGetY(totalItems, buyQty, freeQty) {
    const cycle = buyQty + freeQty;
    const cycles = Math.floor(totalItems / cycle);
    const baseFree = cycles * freeQty;
    const paidAfterBaseFree = totalItems - baseFree;
    const nextPaidThreshold = (cycles + 1) * buyQty;
    const nextCycleEnd = nextPaidThreshold + freeQty;
    const extraFree =
        nextPaidThreshold <= paidAfterBaseFree && paidAfterBaseFree < nextCycleEnd
            ? paidAfterBaseFree - nextPaidThreshold
            : 0;
    return Math.max(0, Math.floor(baseFree + extraFree));
}

function computeTierAllocation(totalItems, tier) {
    const betterCycle = tier.betterBuy + tier.betterFree;
    const betterCycles = Math.floor((totalItems + tier.betterFree) / betterCycle);
    const remainder = Math.max(0, totalItems - betterCycles * betterCycle);
    const lowerCycle = tier.lowerBuy + tier.lowerFree;
    const lowerCycles = Math.floor((remainder + tier.lowerFree) / lowerCycle);

    return {
        betterQty: betterCycles * tier.betterFree,
        betterCycles,
        lowerQty: lowerCycles * tier.lowerFree,
        lowerCycles,
    };
}

function computeFirstThresholdRewardQty(totalItems, buyQty, freeQty) {
    return Math.max(0, Math.floor((totalItems + freeQty) / (buyQty + freeQty)) * freeQty);
}

function enableBanarasAutoProductRewards(order) {
    for (const programId of BANARAS_AUTO_PRODUCT_PROGRAM_IDS) {
        const program = order.models["loyalty.program"].get(programId);
        for (const reward of program?.reward_ids || []) {
            order.uiState.disabledRewards.delete(reward.id);
        }
    }
}

function autoRewardInfoForProgram(order, programId, claimableRewards = []) {
    const claimable = claimableRewards.find(
        ({ reward }) => reward.program_id?.id === programId
    );
    if (claimable) {
        return claimable;
    }

    const pointChange = Object.values(order.uiState.couponPointChanges || {}).find(
        (change) => (change.program_id?.id || change.program_id) === programId
    );
    const program = order.models["loyalty.program"].get(programId);
    if (!pointChange || !program) {
        return null;
    }
    const points = order._getRealCouponPoints(pointChange.coupon_id);
    const reward = program.reward_ids.find(
        (candidate) =>
            candidate.reward_type === "product" && points >= candidate.required_points
    );
    return reward ? { coupon_id: pointChange.coupon_id, reward } : null;
}

function lineMatchesRewardRules(line, reward) {
    if (line.is_reward_line || !line.product_id) {
        return false;
    }
    if (reward.reward_product_ids?.length) {
        return reward.reward_product_ids.some((product) => product.id === line.product_id.id);
    }
    return reward.program_id.rule_ids.some(
        (rule) => rule.any_product || rule.validProductIds?.has(line.product_id.id)
    );
}

function normalizeBanarasTierRewards(order) {
    let changed = false;

    for (const tier of BANARAS_TIER_RULES) {
        const betterLines = order.lines.filter(
            (line) => line.reward_id?.program_id?.id === tier.betterProgramId
        );
        const lowerLines = order.lines.filter(
            (line) => line.reward_id?.program_id?.id === tier.lowerProgramId
        );
        if (!betterLines.length && !lowerLines.length) {
            continue;
        }

        const betterReward = betterLines[0]?.reward_id;
        const lowerReward = lowerLines[0]?.reward_id;
        const ruleReward = betterReward || lowerReward;
        const totalQualifyingQty = order.lines.reduce(
            (sum, line) => sum + (lineMatchesRewardRules(line, ruleReward) ? line.qty : 0),
            0
        );
        const allocation = computeTierAllocation(totalQualifyingQty, tier);

        betterLines.slice(1).forEach((line) => {
            line.delete();
            changed = true;
        });
        lowerLines.slice(1).forEach((line) => {
            line.delete();
            changed = true;
        });

        if (betterLines[0] && allocation.betterQty <= 0) {
            betterLines[0].delete();
            changed = true;
        } else if (betterLines[0] && betterLines[0].qty !== allocation.betterQty) {
            betterLines[0].setQuantity(allocation.betterQty, true);
            betterLines[0].points_cost =
                allocation.betterCycles * betterReward.required_points;
            changed = true;
        }

        if (lowerLines[0] && allocation.lowerQty <= 0) {
            lowerLines[0].delete();
            changed = true;
        } else if (lowerLines[0] && lowerLines[0].qty !== allocation.lowerQty) {
            lowerLines[0].setQuantity(allocation.lowerQty, true);
            lowerLines[0].points_cost = allocation.lowerCycles * lowerReward.required_points;
            changed = true;
        }
    }

    return changed;
}

function lineUnitPrice(line) {
    const qty = Math.abs(line.getQuantity?.() || line.qty || 0) || 1;
    return Math.abs(line.prices?.total_included || line.getPriceWithTax?.() || 0) / qty;
}

function bubbleRewardLines(order) {
    return order.lines.filter(
        (line) => line.reward_id?.program_id?.id === BUBBLE_TEA_PROGRAM_ID
    );
}

function bubbleQualifyingQty(order, reward) {
    return order.lines.reduce(
        (sum, line) => sum + (lineMatchesRewardRules(line, reward) ? line.qty : 0),
        0
    );
}

function chooseBubbleRewardProduct(order, reward) {
    const rewardProductIds = new Set(reward.reward_product_ids.map((product) => product.id));
    const ruleProductIds = new Set(
        reward.program_id.rule_ids.flatMap((rule) => Array.from(rule.validProductIds || []))
    );
    const candidates = order.lines.filter(
        (line) =>
            !line.is_reward_line &&
            line.product_id &&
            rewardProductIds.has(line.product_id.id) &&
            (!ruleProductIds.size || ruleProductIds.has(line.product_id.id)) &&
            line.getQuantity() > 0
    );
    candidates.sort((a, b) => lineUnitPrice(a) - lineUnitPrice(b));
    return candidates[0]?.product_id || null;
}

function autoApplyBubbleTeaReward(order) {
    const claimable = order
        .getClaimableRewards(false, BUBBLE_TEA_PROGRAM_ID, true)
        .find(({ reward }) => reward.program_id?.id === BUBBLE_TEA_PROGRAM_ID);
    const existingLines = bubbleRewardLines(order);

    if (!claimable) {
        existingLines.forEach((line) => line.delete());
        return existingLines.length > 0;
    }

    const { coupon_id, reward } = claimable;
    const product = chooseBubbleRewardProduct(order, reward);
    const desiredQty = computeBuyXGetY(bubbleQualifyingQty(order, reward), 3, 1);
    if (!product) {
        existingLines.forEach((line) => line.delete());
        return existingLines.length > 0;
    }
    if (desiredQty <= 0) {
        existingLines.forEach((line) => line.delete());
        return existingLines.length > 0;
    }

    const existingForProduct = existingLines.find((line) => line._reward_product_id?.id === product.id);
    existingLines
        .filter((line) => line !== existingForProduct)
        .forEach((line) => line.delete());

    if (existingForProduct) {
        let changed = existingLines.length > 1;
        if (existingForProduct.qty !== desiredQty) {
            existingForProduct.setQuantity(desiredQty, true);
            changed = true;
        }
        const pointsCost = desiredQty * reward.required_points;
        if (existingForProduct.points_cost !== pointsCost) {
            existingForProduct.points_cost = pointsCost;
            changed = true;
        }
        return changed;
    }

    const result = order._applyReward(reward, coupon_id, {
        product,
        quantity: desiredQty,
        cost: desiredQty * reward.required_points,
    });
    return result === true || existingLines.length > 0;
}

function chooseRewardProductFromOrder(order, reward) {
    const rewardProductIds = new Set(reward.reward_product_ids.map((product) => product.id));
    const candidates = order.lines.filter(
        (line) =>
            !line.is_reward_line &&
            line.product_id &&
            (rewardProductIds.size
                ? rewardProductIds.has(line.product_id.id)
                : lineMatchesRewardRules(line, reward)) &&
            line.getQuantity() > 0
    );
    candidates.sort((a, b) => lineUnitPrice(a) - lineUnitPrice(b));
    return candidates[0]?.product_id || reward.reward_product_ids[0] || null;
}

function applyTierRewardLine(order, rewardInfo, desiredQty, desiredCycles) {
    const reward = rewardInfo?.reward;
    if (!reward) {
        return false;
    }

    const lines = order.lines.filter((line) => line.reward_id?.program_id?.id === reward.program_id.id);
    if (desiredQty <= 0) {
        lines.forEach((line) => line.delete());
        return lines.length > 0;
    }

    const product = chooseRewardProductFromOrder(order, reward);
    if (!product) {
        lines.forEach((line) => line.delete());
        return lines.length > 0;
    }

    const keeper = lines.find((line) => line._reward_product_id?.id === product.id);
    lines.filter((line) => line !== keeper).forEach((line) => line.delete());

    if (keeper) {
        let changed = lines.length > 1;
        if (keeper.qty !== desiredQty) {
            keeper.setQuantity(desiredQty, true);
            changed = true;
        }
        const pointsCost = desiredCycles * reward.required_points;
        if (keeper.points_cost !== pointsCost) {
            keeper.points_cost = pointsCost;
            changed = true;
        }
        return changed;
    }

    order.applyRewardLine({
        product_id: reward.discount_line_product_id,
        price_unit: -order.currency.round(
            product.getPrice(order.pricelist_id, desiredQty, 0, false, product)
        ),
        tax_ids: product.taxes_id,
        qty: desiredQty,
        reward_id: reward,
        is_reward_line: true,
        _reward_product_id: product,
        coupon_id: rewardInfo.coupon_id,
        points_cost: desiredCycles * reward.required_points,
        reward_identifier_code: crypto.randomUUID(),
    });
    return true;
}

function autoApplyBanarasTierRewards(order) {
    let changed = false;
    const rewards = order.getClaimableRewards(false, false, true);

    for (const tier of BANARAS_TIER_RULES) {
        const betterRewardInfo = autoRewardInfoForProgram(
            order,
            tier.betterProgramId,
            rewards
        );
        const lowerRewardInfo = autoRewardInfoForProgram(
            order,
            tier.lowerProgramId,
            rewards
        );
        const ruleReward = betterRewardInfo?.reward || lowerRewardInfo?.reward;
        if (!ruleReward) {
            changed = applyTierRewardLine(order, { reward: { program_id: { id: tier.betterProgramId } } }, 0, 0) || changed;
            changed = applyTierRewardLine(order, { reward: { program_id: { id: tier.lowerProgramId } } }, 0, 0) || changed;
            continue;
        }

        const totalQualifyingQty = order.lines.reduce(
            (sum, line) => sum + (lineMatchesRewardRules(line, ruleReward) ? line.qty : 0),
            0
        );
        const allocation = computeTierAllocation(totalQualifyingQty, tier);

        const betterChanged = applyTierRewardLine(
                order,
                betterRewardInfo,
                allocation.betterQty,
                allocation.betterCycles
            );
        const lowerChanged = applyTierRewardLine(
                order,
                lowerRewardInfo,
                allocation.lowerQty,
                allocation.lowerCycles
            );
        changed = betterChanged || lowerChanged || changed;
    }

    return changed;
}

function autoApplyRoyalPaanRewards(order) {
    let changed = false;
    const rewards = order.getClaimableRewards(false, false, true);

    for (const programId of ROYAL_PAAN_PROGRAM_IDS) {
        const rewardInfo = autoRewardInfoForProgram(order, programId, rewards);
        if (!rewardInfo) {
            changed =
                applyTierRewardLine(
                    order,
                    { reward: { program_id: { id: programId } } },
                    0,
                    0
                ) || changed;
            continue;
        }

        const qualifyingQty = order.lines.reduce(
            (sum, line) =>
                sum + (lineMatchesRewardRules(line, rewardInfo.reward) ? line.qty : 0),
            0
        );
        const desiredQty = computeFirstThresholdRewardQty(qualifyingQty, 3, 1);
        changed =
            applyTierRewardLine(order, rewardInfo, desiredQty, desiredQty) || changed;
    }
    return changed;
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
        const rewardName = rewardLineDisplayName(this);
        if (rewardName) {
            return {
                name: rewardName,
                attributeString: posUtils.constructAttributeString(this),
            };
        }
        const iceCreamLabel = iceCreamOptionLabel(this);
        if (iceCreamLabel) {
            return {
                name: iceCreamLabel,
                attributeString: posUtils.constructAttributeString(this),
            };
        }
        const group = comboGroupName(this);
        if (group) {
            return {
                name: `${group}: ${productName(this)}`,
                attributeString: posUtils.constructAttributeString(this),
            };
        }
        return {
            name: productName(this),
            attributeString: posUtils.constructAttributeString(this),
        };
    },
});

patch(PosOrder.prototype, {
    getClaimableRewards(coupon_id = false, program_id = false, auto = false) {
        const rewards = super.getClaimableRewards(coupon_id, program_id, auto);
        const existingRewardIds = new Set(rewards.map(({ reward }) => reward.id));
        const customProgramIds = new Set(
            [...BANARAS_AUTO_PRODUCT_PROGRAM_IDS].filter(
                (programId) => !program_id || programId === program_id
            )
        );

        if (customProgramIds.size) {
            for (const pointChange of Object.values(this.uiState.couponPointChanges || {})) {
                const couponId = pointChange.coupon_id;
                if (coupon_id && couponId !== coupon_id) {
                    continue;
                }
                const program = this.models["loyalty.program"].get(pointChange.program_id);
                if (!program || !customProgramIds.has(program.id)) {
                    continue;
                }
                for (const reward of program.reward_ids) {
                    if (
                        existingRewardIds.has(reward.id) ||
                        reward.reward_type !== "product" ||
                        this._getRealCouponPoints(couponId) < reward.required_points ||
                        (auto && this.uiState.disabledRewards.has(reward.id))
                    ) {
                        continue;
                    }
                    rewards.push({ coupon_id: couponId, reward });
                    existingRewardIds.add(reward.id);
                }
            }
        }

        const claimablePrograms = new Set(
            rewards.map(({ reward }) => reward.program_id?.id).filter(Boolean)
        );
        const obsoletePrograms = new Set();

        for (const tier of BANARAS_TIER_RULES) {
            if (claimablePrograms.has(tier.betterProgramId)) {
                const betterReward = rewards.find(
                    ({ reward }) => reward.program_id?.id === tier.betterProgramId
                )?.reward;
                const totalQualifyingQty = this.lines.reduce(
                    (sum, line) => sum + (lineMatchesRewardRules(line, betterReward) ? line.qty : 0),
                    0
                );
                const allocation = computeTierAllocation(totalQualifyingQty, tier);
                if (allocation.lowerQty <= 0) {
                    obsoletePrograms.add(tier.lowerProgramId);
                }
            }
        }

        return rewards.filter(({ reward }) => !obsoletePrograms.has(reward.program_id?.id));
    },

    _applyReward() {
        const result = super._applyReward(...arguments);
        normalizeBanarasTierRewards(this);
        return result;
    },

    _updateRewardLines() {
        const result = super._updateRewardLines(...arguments);
        return result || normalizeBanarasTierRewards(this);
    },
});

async function postProcessBanarasRewards(pos, order) {
    if (!pos?.orderUpdateLoyaltyPrograms || !order || order.finalized) {
        return;
    }
    if (order.uiState.banarasPostRewardUpdateScheduled) {
        return;
    }
    order.uiState.banarasPostRewardUpdateScheduled = true;
    setTimeout(async () => {
        order.uiState.banarasPostRewardUpdateScheduled = false;
        if (order.finalized || pos.getOrder?.() !== order) {
            return;
        }
        enableBanarasAutoProductRewards(order);
        await pos.orderUpdateLoyaltyPrograms();
        autoApplyBubbleTeaReward(order);
        autoApplyRoyalPaanRewards(order);
        autoApplyBanarasTierRewards(order);
        normalizeBanarasTierRewards(order);
    }, 1000);
}

patch(PosStore.prototype, {
    async afterProcessServerData() {
        const result = await super.afterProcessServerData(...arguments);
        rebuildBanarasProgramMaps(this.models);
        if (!this.selectedCategory && this.models?.["pos.category"]?.get(PAAN_CATEGORY_ID)) {
            this.setSelectedCategory(PAAN_CATEGORY_ID);
        }
        return result;
    },

    get productToDisplayByCateg() {
        const groups = super.productToDisplayByCateg;
        if (this.selectedCategory?.id !== PAAN_CATEGORY_ID || this.searchProductWord?.trim()) {
            return groups;
        }
        const paanGroup = groups.find((group) => Number(group[0]) === PAAN_CATEGORY_ID);
        if (!paanGroup) {
            return groups;
        }
        return groupPaanProducts(paanGroup[1]);
    },

    updateRewards() {
        const result = super.updateRewards(...arguments);
        postProcessBanarasRewards(this, this.getOrder?.());
        return result;
    },
});

patch(OrderSummary.prototype, {
    _setValue() {
        const result = super._setValue(...arguments);
        postProcessBanarasRewards(this.pos, this.currentOrder);
        return result;
    },
});
