# Makerlab Return Processor — v1.0.5-test

**Release type:** Manual-reconciliation / recovery UX enhancement

## Added

1. **Make Recoverable** button in Scan History. Converts an existing uncompleted history record into a durable Recovery record. Previously recorded Odoo evidence is preserved and its automated retry remains locked.
2. **Enter Manual Odoo / TC-IN** dialog. Enter or correct the saved Helpdesk ticket URL, ticket title, TC/IN ID and transfer URL for each returned-item classification/decision group; pre-populates any available identifiers.
3. Operator acknowledgment, manual repair notes, and exact Order-ID confirmation required before saving manual information.
4. The main app now restores the manual checkpoint and displays **Confirm Manual TC/IN & File Lark**, using the existing audit/confirmation and Lark-only submission code.
5. JSON audit metadata: `manual_recovery_events` and `manual_odoo_reconciliation_history` (including previous transfer IDs/URLs). These events are retained when a Lark-pending checkpoint is regenerated.
6. Recovery-only scans with a missing History mirror can reconstruct their History entry when manual reconciliation is saved.

## Preserved

- Existing v1.0.4.9-test `odoo.py`, including Zero Demand Warning → Keep lines, validation handling, warehouse approval, QC and separate classification groups.
- Existing v1.0.4.8-test `lark.py` rules for TikTok source groups and manual item selections.
- Previous scan/restore IDs, existing Odoo tickets and transfers, configurable New→MNL/Stock or BLC/Stock, Lark-only retry, duplicate filing protection and editable Scan History.
- Existing `ui_theme.py`, marketplace modules and browser profiles.

## Technical behavior

- Manual transfers are registered as **`workflow_state=manual_review`**, `odoo_checkpoint.stage=manual_review`, `resume_safe=False`, `odoo_results=None` until the operator confirms actual Odoo work using the existing Lark-only button.
- The same Odoo validator `confirm_existing_transfers_for_lark()` verifies ticket/transfer URLs and grouping before registration and again before filing.
- The successful Lark-only confirmation converts the checkpoint into `odoo_returns_complete`/`lark_pending` before invoking Lark, and never clicks Odoo Return or Validate.
- Completion updates the original `scan_history.json` record before removing its active Recovery point.

## Limitations / testing

Offline tests (storage, Tkinter GUI under Xvfb, integration with existing application modules, mocked Lark-only submission) passed. Live authenticated Odoo and Lark execution is **not** verified. The operator must personally review the existing Odoo transactions and check that Lark has not already received the same items.
