# Makerlab Return Processor v1.0.4-test

## Source baseline

- Desktop/recovery: `main.py` from v1.0.3.2-test, the latest main module supplied for this project.
- Odoo processing: `odoo.py` from v1.0.3.8-test, preserving the November 11 Zero Demand Warning / **Keep lines** behavior, Validate compatibility, warehouse handoff, separate QC routes, and transfer recovery safeguards.
- JSON persistence: existing `workflow_store.py`.
- History/Recovery: existing `history_window.py`.

## New: Save for Recovery

- **Save for Recovery** is now available in the top toolbar after a return has been loaded.
- Saves unfinished scans **without confirming the item decision and without submitting anything to Odoo or Lark**.
- Captures the current selected item's editable amount, classification, tag, decision, status, grade and remarks, along with all stored item rows.
- Updates the **same original scan ID** and makes it recoverable through the existing **Recovery** window.
- Uses a new `manually_saved` workflow state for incomplete scans; already-confirmed scans retain their `confirmed` state.
- Writes and verifies `restore_points.json` before updating the Scan History audit record; warns if the latter fails.
- Once Odoo has begun, manual draft save is disabled. The program's existing, stricter automatic Odoo checkpoints remain authoritative.

## New: Settings and Brand New routing

- New **Settings** toolbar action, backed by `data/settings.json` with the existing atomic-write and backup pattern.
- **Default Brand New destination:** `MNL/Stock` (unchanged default), with `BLC/Stock` as the other allowed choice.
- Settings also offers **Apply to current scan** when it has no Odoo/Lark progress.
- A separate **Brand New destination** dropdown in the scan panel permits per-case overrides without changing the default.
- Choice is stored in Scan History and recovery snapshots, and frozen into the Odoo ticket checkpoint **before** the ticket is created.
- Older scans with no destination field continue using `MNL/Stock`, even if the new app default has changed.
- New-stock Odoo routing, existing-transfer destination verification, and New warehouse-handoff completion recognize **both** locations.
- Unsealed and Defective QC routes are unchanged.
- Changing the choice after an Odoo checkpoint/results exists is blocked to protect already-recorded stock transfers.

## Unchanged

- Shopee, Lazada, TikTok return extraction.
- The current Odoo Helpdesk creation, SKU/Demand editing, warehouse approval and QC flows.
- Existing Odoo duplicate-prevention checkpoints and recovery safeguards.
- Lark filing and its transfer-to-item matching behavior.
- Existing Windhawk-compatible Tkinter styling and app-specific Chrome profile.

## Validation

Local, **offline** tests passed:

1. Settings defaults, validation, persistence after restart and atomic JSON path.
2. Manual save before confirmation, with per-item remarks and partial classifications.
3. Restoring the same scan ID and its saved per-order destination.
4. Updating the default without altering a previously saved scan.
5. Actual Tkinter Settings dialog can change and save the default.
6. New-stock Odoo route selection for `MNL/Stock` and `BLC/Stock`.
7. Existing transfer verification rejects a mismatched destination.
8. Odoo checkpoint saves the chosen destination and refuses invalid choices.
9. Two-classification sequence: New (`BLC/Stock`) then Defective, separate transfers on the same ticket; checkpoint consistency.
10. All four modules compile and their imports work with the current uploaded dependencies.

**Not tested:** an authenticated, live Odoo transfer to `BLC/Stock` or live production approval/QC flows. Do a controlled test with a suitable order before relying on this test release.
