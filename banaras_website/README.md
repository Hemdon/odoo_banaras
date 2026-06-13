# Banaras Paan Website — Odoo module

Custom **Home page** for the Banaras Paan Odoo site (`pos.banaraspaan.com`),
migrated from the legacy WordPress site. Built with native Odoo/Bootstrap
blocks so it stays editable in the Website Builder after install.

## What it does
- Replaces the default Odoo home page with a branded, responsive layout:
  Hero → Intro → "More than a paan shop" → 4 category cards → stats →
  two location blocks (with hours + directions) → order CTA.
- Brand palette from the logo: indigo `#232c84`, green `#3aa935`, sky `#2ba8e0`, gold `#f2a60c`.
- SEO: semantic `<h1>/<h2>`, meta description/keywords + Open Graph tags,
  and JSON-LD `Restaurant` structured data for both Harrow branches.

## File layout
```
banaras_website/
├── __manifest__.py
├── __init__.py
├── views/homepage.xml          # home page content + SEO meta (QWeb)
└── static/src/css/banaras.css  # brand styling
```

## Target environment
Confirmed on the live instance: **Odoo 19.0 Community Edition, self-hosted**,
multi-company (6 companies). Because it's self-hosted Community, **install the
module directly** (Path A below).

## Install (Path A — self-hosted, this instance)
1. Copy the `banaras_website/` folder into the server's addons path
   (the directory listed in `addons_path` in the Odoo config), then restart Odoo.
2. **Settings → Developer Tools → Activate the developer mode** (it's currently off).
3. **Apps → ⋮ → Update Apps List**.
4. Search **"Banaras Paan Website"** → **Install**.
5. Visit `/` — the new home page renders; `/about-us` is published with a menu item.

> Multi-company note: this DB has 6 companies. The home page override is global
> (applies to every website) unless scoped to one website. Confirm whether all
> branches share one website or each has its own before installing.

## Fallback (no filesystem access — paste via editor)
1. Developer mode on → **Settings → Technical → Website → Views** (or the page's
   **Edit source**).
2. Paste the markup inside `views/homepage.xml`'s `<div id="wrap">…</div>` into the
   Home page body, and the About markup as a new page.
3. Add `static/src/css/banaras.css` via Website → Configuration →
   **Custom Code → Head**, wrapped in `<style>…</style>`.

## After install — finish in the UI (2 minutes)
- **Logo / favicon:** Website → Configuration → Website → upload the Banaras
  Paan logo (the green-leaf mark) if not already set.
- **SEO title:** open `/`, **Edit → Optimize SEO**, set the page title to
  `Banaras Paan — Authentic Sweet Paan, Bubble Tea & Desserts in Harrow`.
  (The description/keywords/OG tags are already injected by the module.)
- **Images:** the design uses icons + brand gradients so it looks complete
  immediately. To add real photos, edit the Hero / category cards in the
  builder and drop images in.
- **Links:** category cards and CTAs point to `/shop`. Once the
  "Local Orders" / "UK Wide Orders" pages exist, repoint the hero buttons.

## Open decisions still pending (see ../MIGRATION_PLAN.md §5)
- Final top menu structure
- Canonical email (`info@` vs `sales@`)
- Footer social links (currently LinkedIn in Odoo; source uses Instagram)
