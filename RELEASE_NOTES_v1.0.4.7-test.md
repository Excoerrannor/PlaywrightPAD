# Makerlab Return Processor - v1.0.4.7-test

Based on v1.0.4.6-test (November 13, 2026). Patch scope: `odoo.py`, `main.py`, and `lark.py` only.

## 1. Odoo Zero Demand Warning: retain lines

The automation recognizes the exact `Zero Demand Warning` dialog and clicks the specific `Keep lines` action (`button[name="process"][type="object"]`) whenever the verified warning appears after Validate and during subsequent return/QC processing. The follow-up handler also checks after each QC confirmation and can consume consecutive warnings. It supports an existing New-stock return in a warning state without clicking Validate a second time.

**Safety gates retained:** the recorded `TC/IN` identifier must match the open transfer; exact requested SKU/quantity must match Demand; unrelated lines must have zero Demand; the explicit Keep lines button must be present. An uncertain click, wrong product, or unexpected dialog stops for Manual Review. **It never clicks `Remove lines`, repeats Validate, or submits another Return to clear this warning.**

## 2. Explicit Retry Lark Only button

When Odoo is already recorded as complete and Lark has not finished, the ordinary Submit button changes label and callback to **Retry Lark Only**. The control is enabled after the error dialog (and the processing-busy flag is cleared before displaying the dialog). It never calls Odoo ticket/stock operations. Before retrying, it warns the operator to check for partially submitted Lark entries and verifies a saved `lark_pending` checkpoint. The existing case and TC/IN identifiers are preserved.

## 3. TikTok multi-return source reconciliation

The earlier generic "TikTok return-card IDs do not match" now reports **which Return Order IDs are missing or unexpected** and any unit-count mismatch. All source return-card units must be represented before filing. This also runs before a new TikTok scan is confirmed, so an incomplete multi-card scan cannot create a new Odoo Helpdesk ticket.

Lark now validates and plans every form record before submitting the first. This avoids submitting the first Lark record when a subsequent one is invalid. Network failures after a successful submission may still cause a partial filing, so rechecking Lark is required before retrying.

### Existing problematic TikTok case

The provided screenshot shows Order ID `586832186683459538`, total refund PHP 2,162.80, and only one selected product row (`MLE09955`, QTY 1). The earlier captured TikTok source comprises four independent Return Order IDs and seven units in total. That saved scan needs reconciliation; enabling Retry Lark Only **will not override missing source items or invent refund amounts**. Review the saved return-card IDs, products, and Odoo transfers before continuing. Do not submit another Odoo ticket.

## Compatibility and testing

- Python compilation and import compatibility with the v1.0.4.6-test desktop modules passed.
- Offline Chromium simulation: exact Keep lines, repeated warnings, incorrect Demand, wrong TC/IN protections passed.
- 4-card TikTok regression: tracking/order/return-ID search, 7 units, PHP 2,162.80 refund, per-return Lark values, split-card protections passed.
- GUI button-state unit test: Odoo complete / Lark pending => Retry Lark Only enabled, busy => disabled passed.
- **Live Odoo/TikTok/Lark submissions were NOT performed.**

## Files to replace

1. `main.py`
2. `odoo.py`
3. `lark.py`

Do not overwrite `tiktok.py`, `workflow_store.py`, `history_window.py`, `ui_theme.py`, `data/`, or `OdooProfile/`. Back up current files and `data/` before installing.
