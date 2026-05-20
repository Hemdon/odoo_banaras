# Banaras Paan — Odoo + Goodtill Project Handoff

**Last updated:** 2026-05-20  
**GitHub:** https://github.com/Hemdon/odoo_banaras  
**Server:** `46.202.140.75` (alias: `odoo` in `~/.aliases`)

---

## Quick resume prompt (paste into Cursor tomorrow)

```
Continue Banaras Paan Odoo project from CONTINUE_TOMORROW.md in odoo_banaras.
Server: ssh via alias `odoo` (root@46.202.140.75). Odoo DB: Main_Banaras.
POS: Main Register config_id=9, company Banaras - RaynerLane.
Goodtill subdomain: banaraspaan. Check CONTINUE_TOMORROW.md for credentials paths and open items.
```

---

## What’s done

### Server & database
- PostgreSQL DB: **Main_Banaras** on `46.202.140.75`
- Odoo **19.0** running on port **8069**
- SSH: `alias odoo` → `sshpass ssh root@46.202.140.75` (password in `~/.aliases`)

### Companies (Odoo)
| Company | ID | Currency | Chart |
|---------|-----|----------|-------|
| Banaras - RaynerLane | 5 | GBP £ | UK (`uk`) |
| Banaras Paan (parent) | 4 | GBP | UK |
| Banaras - Hatch End | 6 | GBP | UK |

### POS — Rayners Lane
- **Name:** Main Register (matches Goodtill Main Outlet / Main Register)
- **Config ID:** `9`
- **URL:** http://46.202.140.75:8069/pos/ui/9
- **Company:** Banaras - RaynerLane
- **Categories:** 18 Goodtill categories (Paan, Bubble Tea, etc.)
- **Products:** 228 synced from Goodtill Main Outlet; **121 with images**
- **Settings:** `show_product_images=True`, `show_category_images=True`

### Goodtill → Odoo sync (local scripts)
| Script | Purpose |
|--------|---------|
| `goodtill_to_odoo.py --sync` | Products + categories |
| `goodtill_to_odoo.py --sync-images` | Product images from Goodtill S3/API |
| `fix_pos_images.py` | Re-sync images + category tile icons + POS settings |
| `setup_raynerlane_main_register.py` | POS config for Main Register |

### Git
- Repo: **https://github.com/Hemdon/odoo_banaras**
- Secrets in `.env` (gitignored) — copy from `.env.example`

---

## Credentials (local only — NOT in git)

Store in `odoo_banaras/.env`:

```env
GOODTILL_SUBDOMAIN=banaraspaan
GOODTILL_USERNAME=Banaras@Admin
GOODTILL_PASSWORD=<see .env on machine>

ODOO_URL=http://46.202.140.75:8069
ODOO_DB=Main_Banaras
ODOO_USERNAME=banaraspaan.uk@gmail.com
ODOO_PASSWORD=1xOeJ3m53uWZA1!

GOODTILL_OUTLET_ID=02f13246-56ff-404e-84b8-ad3200601295
```

Admin default company set to **Banaras - RaynerLane** (id=5).

---

## Goodtill mapping

| Goodtill | Odoo |
|----------|------|
| Main Outlet (`BNRSUK`) | Rayners Lane branch |
| Main Register | POS config "Main Register" |
| 388 products / 228 sellable | Synced to Odoo |
| 121 with images | `image_1920` on product.template |

**Note:** No separate "Rayners Lane" outlet in Goodtill — uses **Main Outlet** catalog.

Other outlets: Hatch End, Netherlands, Bristol.

---

## How to open POS tomorrow

1. http://46.202.140.75:8069/web/login
2. Login: `banaraspaan.uk@gmail.com` / password from `.env`
3. Database: **Main_Banaras**
4. Company: **Banaras - RaynerLane**
5. http://46.202.140.75:8069/pos/ui/9 **after login**
6. Close old session first if "session already open" → backend: Point of Sale → Close session

**If stuck on login:** Session expired — incognito window or clear cookies for `46.202.140.75`.

---

## Open items / next steps

- [ ] **POS images:** ~107 products still have no Goodtill image — add in Goodtill, then `python3 fix_pos_images.py`
- [ ] **HTTPS for Odoo:** `srv1649615.hstgr.cloud` nginx → port 3000 (KDS only); Odoo is HTTP :8069 only
- [ ] **Hatch End branch:** Separate POS if needed (company id=6)
- [ ] **UK VAT** on products — verify tax rules after chart install
- [ ] **Product variants/modifiers** from Goodtill — not synced yet (top-level only)
- [ ] Reset Odoo password if user changed it

---

## Useful commands

```bash
cd /Users/hemesh/Downloads/BugUp/Claude_Tester/odoo_banaras

# Sync products
python3 goodtill_to_odoo.py --sync

# Sync images
python3 fix_pos_images.py

# SSH to server
odoo   # from terminal with ~/.aliases loaded

# On server — Odoo shell
sudo -u odoo odoo shell -d Main_Banaras -c /etc/odoo/odoo.conf --no-http

# Close stuck POS session (server)
# pos.session search opened → action_pos_session_closing_control
```

---

## Related projects (same machine)

- `Claude_Tester/POS_to_Brevo 2/` — Goodtill → Brevo customer sync
- `Claude_Tester/Banaras_Sales_CallAssitant/` — KDS + Goodtill webhooks (nginx :443 → :3000)

---

## Issues resolved this session

1. Found Main_Banaras DB, reset admin password
2. Set up Rayners Lane POS + UK chart of accounts
3. Synced 228 Goodtill products + 18 categories
4. GBP currency + Main Register naming
5. Synced 121 product images + 11 category images
6. POS login = must authenticate first (session expired redirects to login)
7. Closed stuck POS session blocking register open
