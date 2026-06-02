# Banaras Paan — Odoo + Goodtill Project Handoff

**Last updated:** 2026-05-20  
**GitHub:** https://github.com/Hemdon/odoo_banaras  
**Server:** `187.77.99.211` — SSH: `ssh -i ~/.ssh/id_odoo root@187.77.99.211`  
**Odoo URL:** https://srv1649615.hstgr.cloud  
**Odoo DB:** Main_Banaras  
**Goodtill subdomain:** banaraspaan

---

## Quick resume prompt

```
Continue Banaras Paan Odoo from CONTINUE_TOMORROW.md in odoo_banaras.
Server: ssh -i ~/.ssh/id_odoo root@187.77.99.211
DB: Main_Banaras. POS: Main Register id=9 (Rayners), Hatch End Register id=13.
Goodtill loyalty/promos: goodtill_loyalty.json, setup_goodtill_loyalty.py on server /opt/odoo/custom/
```

---

## What’s done

### Companies
| Company | ID |
|---------|-----|
| Banaras Paan (parent) | 4 |
| Banaras - RaynerLane | 5 |
| Banaras - Hatch End | 6 |

### POS
| Register | Config ID | Company | Pricelist |
|----------|-----------|---------|-----------|
| Main Register | 9 | RaynerLane (5) | Main (1) |
| Hatch End Register | 13 | Hatch End (6) | Hatch End (5) |

- Hatch End `picking_type_id` fixed → company 6 PoS Orders (was demo San Francisco — caused Access Error for Hamish Admin).
- Custom module: `banaras_pos_topping/` (bubble tea toppings on POS).

### Goodtill sync scripts (local + `/opt/odoo/custom/` on server)
| Script | Purpose |
|--------|---------|
| `goodtill_to_odoo.py` | Products, categories, taxes, branch prices |
| `fetch_goodtill_promotions.py` | Export promos to `goodtill_promotions.json` |
| `setup_goodtill_promotions.py` | Sync buy-X-get-Y / % promos → `loyalty.program` |
| `goodtill_loyalty.json` | Loyalty categories + reward tiers (source of truth) |
| `setup_goodtill_loyalty.py` | Tags `GT-Loyalty:*` + Banaras Paan Loyalty programs |
| `setup_hatch_end_pos.py` | Hatch End POS + pricelist |
| `fix_loyalty_pos_trigger.py` | `trigger=auto` for POS promos |
| `fix_loyalty_product_tags.py` | Multi-product rewards via `reward_product_tag_id` |

### Loyalty (Goodtill-style)
- **Earn:** £1 = 5 points (`points_per_currency: 5`), nominative (customer required).
- **Programs:** Banaras Paan Loyalty (Main), Banaras Paan Loyalty (Hatch End) — different point costs per tier.
- **Categories (product tags, not Odoo categories):**
  - `standard_paan`, `delux_paan` — 4 products each (from Goodtill names)
  - `bubble_tea_500ml_hatch` — 10 products (Hatch reward list)
  - `bubble_tea_500ml` — broad match on Main (~33 products); **user will send fixed list later**
- **POS:** Customer → sell → ⋯ Reward → pick tier → choose product. Close/reopen session after config changes.

### Promotions
- Use Goodtill **external** API promos; mapped to Odoo `loyalty.program` with Goodtill display names.
- Branch-specific: Rayners vs Hatch End where duplicated in Goodtill.

---

## Credentials

Local only — copy `.env.example` → `.env` (gitignored). Never commit passwords.

---

## Open items

- [ ] **Main Register 500ml bubble tea** — user to send explicit Goodtill list → new category in `goodtill_loyalty.json`
- [ ] **Import Goodtill customer point balances** → Odoo `loyalty.card`
- [ ] Product variants/modifiers full sync (top-level + bubble tea combos partial)
- [ ] ~107 products still without Goodtill images → `fix_pos_images.py` after Goodtill upload

---

## Useful commands

```bash
cd /Users/hemesh/Downloads/BugUp/Claude_Tester/odoo_banaras

# Deploy custom scripts to server
scp -i ~/.ssh/id_odoo goodtill_loyalty.json setup_goodtill_loyalty.py root@187.77.99.211:/opt/odoo/custom/

# Apply loyalty on server
ssh -i ~/.ssh/id_odoo root@187.77.99.211 \
  'sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d Main_Banaras --no-http < /opt/odoo/custom/setup_goodtill_loyalty.py'

# POS URLs (after login)
# Main:    https://srv1649615.hstgr.cloud/pos/ui/9
# Hatch:   https://srv1649615.hstgr.cloud/pos/ui/13
```

---

## Issues resolved (recent)

1. Promotion Reward button grey — `trigger=auto`, product tags for multi-reward
2. Loyalty categories populated from Goodtill product names
3. Hatch End Access Error on `stock.picking.type` — wrong company picking type on POS config 13
