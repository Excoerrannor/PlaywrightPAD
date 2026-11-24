# Makerlab Return Processor — v1.0.6-test installation

## Purpose

Adds a separate Wrong Item / Scam Lark Base workflow using the supplied Lark form:

https://kjx72am2njb.sg.larksuite.com/share/base/form/shrlgqkLCe66MOX6wjiz9QbGaqb

The base contains exactly four required form fields: Order ID, SKU, Received Item, Status. SKU is formatted `SKU_QTY` (for example, `MLE00001_2`). The available Status values are **Refunded (Seller Fault)**, **Dispute Approved**, **Dispute Rejected**, and **In-Dispute**.

## Install

1. Close Makerlab Return Processor.
2. Back up `C:\PlaywrightPAD\main.py`, `lark.py`, `workflow_store.py`, `history_window.py`, and the entire `C:\PlaywrightPAD\data` folder.
3. Replace those four existing modules and **add** the new `wrong_item_lark.py` in `C:\PlaywrightPAD`.
4. Keep current `odoo.py` from v1.0.5.3-test and every existing marketplace module, browser profile (`OdooProfile`), and JSON file unchanged.
5. Restart. No new Python dependencies are required beyond those used by the existing application.

## Usage

1. Scan the marketplace order normally.
2. Choose **Wrong Item** or **Scam** for the affected row.
3. Fill **Received Item** with the actual received product, and choose **Wrong Item / Scam Status**.
4. The regular Odoo Tag is not required for these classifications, regardless of whether the parcel physically arrived.
5. Save the item, then **Confirm All Items**. The new action is **File Wrong Item / Scam** for an all-special case; mixed orders use the combined workflow.
6. Only the normal physically Returned items go to Odoo. The special items go to the separate Lark Base, one record per affected item. Normal Lark Item Returns records continue to use the original Lark Base.
7. If a later form fails, inspect both Lark Bases for partially submitted records **before retrying**. Scan History / Recovery keeps per-form successful results and skips those saved entries.

The History editor also allows editing Received Item and Wrong Item / Scam Status before external work starts.

## Important limits

- A successful Lark form response is required to mark a submission filed; a browser timeout after Submit is **uncertain**, not proof of failure. Inspect Lark before another attempt.
- This version files the Status value currently selected. It **does not automatically update** an existing Lark Base record when a later marketplace dispute result changes. Extending `dispute_checker.py` can be a separate task.
- The new form has no refund amount field. No amount is invented for these records. Mixed orders use the normal returned-item amounts for the original Item Returns Base.
- The first live filing must be tested in the authenticated Lark browser profile. Tests are offline and mocked, not production submissions.

## Verify

```powershell
& 'C:\PlaywrightPAD\.venv\Scripts\python.exe' -c "from main import ReturnProcessorApp; from wrong_item_lark import plan_wrong_item_filings; print('Wrong Item / Scam integration import OK')"
```
