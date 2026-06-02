# Goodtill → Odoo print & kitchen routing

## Goodtill flags

| Goodtill | Odoo |
|----------|------|
| Send to receipt and email | Customer receipt (normal POS payment / print) |
| Send to kitchen | POS category **Send to Kitchen** → **Kitchen Printer** |
| Send to drinks | POS category **Send to Drinks** → **Drinks Printer** |
| Send to other | POS category **Send to Other** → **Other Printer** |

Routing categories are **not** shown on the POS product grid (only used for printers).

## Both branches

**Main Register** (id=9) and **Hatch End Register** (id=13) use the same three preparation printers and `is_order_printer = True`.

## Re-sync from Goodtill

```bash
python3 fetch_goodtill_print_flags.py
scp goodtill_print_flags.json setup_goodtill_print_routing.py root@SERVER:/tmp/
# run setup via odoo shell (see script header)
```

## Printer IPs

Set real Epson IPs under **Point of Sale → Configuration → Preparation Printers** (currently `0.0.0.0` placeholders).

## Kitchen Display (KDS)

The **Preparation Display** app (`pos_preparation_display`) is not installed on this server. Kitchen/bar tickets use **preparation printers** when staff tap **Order** in POS.

To add a screen KDS like Goodtill, install Odoo Enterprise **Preparation Display** if your subscription includes it.
