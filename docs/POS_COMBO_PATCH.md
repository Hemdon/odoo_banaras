# POS combo topping load fix

Odoo only preloads `product.combo.item` choices for templates with **type = combo**.
Bubble tea uses **type = consu** + `combo_ids` for toppings, so the POS popup showed empty lists.

## Patch (2 lines in `point_of_sale/models/product_template.py`)

```python
# load_product_from_pos (~line 92)
if product_tmpl.combo_ids:   # was: if product_tmpl.type == 'combo':

# _load_pos_data_search_read (~line 207)
product_combo = products.filtered(lambda p: p.combo_ids)  # was: p['type'] == 'combo'
```

After patching: `systemctl restart odoo`, then **close all POS sessions** and open a new one.
