# Makerlab Return Processor - Odoo Product Selector Compatibility Fix

## Date
November 5, 2026

## Observed Odoo change
In Helpdesk ticket Product selection, the dropdown now renders a product description followed by a separate bold SKU span:

```html
<a role="option">
  2600mAh PKCELL 18650 3.7V Lithium Ion Battery Cell
  <span class="text-muted"><span class="text-primary fw-bold">MLE04875</span></span>
</a>
```

The earlier `^[MLE04875]` accessible-name selector no longer matches that option.

## Fix
- Target the `product_id` many2one combobox directly.
- Search by SKU as before.
- Match the SKU **exactly** inside `span.text-primary.fw-bold` in the product's dropdown option.
- Retain the older `[SKU] Product description` matching path.
- Never select `Create`, `Create and edit`, or `Search more` actions as the product.
- Stop if more than one exact product option is found, rather than selecting arbitrarily.
- Do not change ticket creation, Odoo return quantities, routing, Lark, recovery JSON, UI, or marketplace handlers.

## Installation
1. Close the processor.
2. Back up `C:\PlaywrightPAD\odoo.py`.
3. Copy the updated `odoo.py` into `C:\PlaywrightPAD`.
4. Restart the Python application, or rebuild your PyInstaller EXE if using a compiled build.

## Existing ticket caution
The Helpdesk ticket is created **before** product selection. If an earlier run failed on the product dropdown, verify whether that ticket already exists before retrying a full submission. This specific patch does not add a new restore checkpoint for that stage.

## Validation
Offline Chromium checks were performed with the Nov 5 Odoo HTML provided, a legacy `[SKU]` option, mismatched SKU values, a `Create`-only dropdown, and duplicate exact SKU options. These checks passed. A live Odoo ticket submission was not performed.
