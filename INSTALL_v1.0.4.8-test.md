# Makerlab Return Processor - v1.0.4.8-test

## Installation (Windows)

Base: v1.0.4.7-test (or unchanged v1.0.4.5 workflow-store/history modules).

1. Close the Return Processor.
2. Back up `C:\PlaywrightPAD\main.py`, `lark.py`, and **the entire** `C:\PlaywrightPAD\data` folder.
3. Replace **both** `C:\PlaywrightPAD\main.py` and `C:\PlaywrightPAD\lark.py` with the files in this release.
4. Leave `odoo.py`, `tiktok.py`, `shopee.py`, `lazada.py`, `history_window.py`, `workflow_store.py`, `ui_theme.py`, `OdooProfile`, and `data` unchanged.
5. Restart the app.

## Recover the reported TikTok case

1. Restore Order `586832186683459538` from **Recovery**. Do not run Odoo again.
2. Confirm the existing TC/IN is correct, and check whether any Lark record has already been partially submitted.
3. Ensure the retained SKU(s) each have an accurate **Amount**. This amount is the **total for the selected item row**. It must not exceed the source refund for that item's TikTok Return Order ID.
4. Click **Retry Lark Only**.
5. If the saved source totals do not match your intentionally edited item selection, a new dialog summarizes original source vs selected units and refund amounts.
6. Choose Yes only if the retained items are intentional. Enter a reason and type the exact marketplace Order ID for confirmation.
7. The processor writes the edited-selection details into the existing Recovery/Scan History records, and verifies the save before opening Lark. The previously recorded Odoo ticket/transfer is reused, not recreated.
8. Review the Lark submission result and updated Scan History. If a submitted result is uncertain, check Lark before retrying.

## Safeguards

- TikTok original return-card IDs, quantities, and refund totals remain in the saved scan; they are not replaced with the partial selection.
- Selected amounts are **operator-assigned**, not automatically allocated from excluded return cards.
- Missing/unknown Return Order IDs, missing Amounts, selected units larger than source units, and allocations above an original return card's total **are blocked**.
- The chosen items must match all existing Odoo transfer SKU/quantity/classification mappings. Mismatches are **blocked**; no new Odoo operations occur.
- Any later change to SKU, quantity, amount, classification, status, or other Lark-critical data requires confirmation again.
- The entire confirmation and current item selection must be durably present in the Recovery JSON before Lark is contacted.

## Testing

- Python syntax compilation and importing updated app with other current project modules passed.
- 16 isolated offline tests passed, including a simulated Lark-only submission for the single selected SKU.
- No authenticated production TikTok, Odoo, or Lark requests were performed; verify first with a controlled case.
