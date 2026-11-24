# Release Notes - Makerlab Return Processor v1.0.4.8-test

## Fix: intentional TikTok item changes should not be treated as an incomplete scan

**Symptom:** After a multi-return TikTok scan had correctly loaded four source return cards, an operator manually deleted or edited items. The v1.0.4.7 Lark-only retry insisted that all seven original units were still present and displayed "TikTok Source Reconciliation Required." This also happened with a valid existing TC/IN and completed Odoo workflow.

**Updated behavior:** The original complete source is still required at initial TikTok extraction. Once items have been intentionally changed, the operator can explicitly confirm a curated subset (no blanket safety bypass):

- Original marketplace return cards/totals stay unchanged in the audit record.
- Only the selected, operator-approved SKU/QTY and manually entered **per-row refund amounts** will be filed in Lark.
- A new confirmation screen shows source/selected unit counts, return-card counts, and refunds. It requires a rationale and exact Order ID.
- Confirmation is fingerprinted to the selected item list and original source values. Subsequent changes invalidate it.
- Scan History and Recovery retain the operator confirmation with time, reason, selected and excluded return card IDs, selection quantities, and selected refund amounts.
- Lark-only retry verifies this checkpoint before opening Lark, and never performs any Odoo action.
- Initial Confirm All Items also supports intentional changes *before* Odoo processing, with the same confirmation.
- Existing Odoo transfer-to-selected-item matching and duplicate prevention stay active. A selection that no longer matches existing Odoo records still cannot be filed.

### Example from the reported case

- Original TikTok Order ID: `586832186683459538`.
- Source totals: four TikTok return cards / seven units / PHP 2,162.80.
- Manually retained item illustrated in screenshot: `MLE09955`, QTY 1, Amount PHP 657.00.
- After explicit approval, Lark should file only the selected item and its manually verified PHP 657.00 allocation, **if** the recorded Odoo transfer matches that item.
- The source PHP 2,162.80 is still preserved for audit, not sent as the selected Lark record value.

### Changed files

- `main.py`: edited-selection confirmation on initial confirmation or Lark-only retry; source selection audit; durable save verification; edit invalidation.
- `lark.py`: audited curated-selection validation, confirmed amount calculations, exact Odoo transfer matching and safeguards.

### Unchanged files

`odoo.py`, `tiktok.py`, `workflow_store.py`, `history_window.py`, `ui_theme.py`, other platforms, and JSON storage schemas. No Odoo validation/Return logic is modified.

### Verification

16 offline unit and desktop-action tests passed; modules compile and current imports work. No live Lark submission or actual stock movement was executed.
