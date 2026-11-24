# Makerlab Return Processor — v1.0.6-test

## New: dedicated Wrong Item / Scam Lark workflow

Connected a new form endpoint:

`https://kjx72am2njb.sg.larksuite.com/share/base/form/shrlgqkLCe66MOX6wjiz9QbGaqb`

The four form fields and IDs were verified from the user-provided November 18, 2026 HTML:

| Field | ID | Filing rule |
|---|---|---|
| Order ID | `fldF74VqNi` | Original marketplace Order ID |
| SKU | `fldzpfI9B4` | Supposed SKU plus `_QTY` suffix |
| Received Item | `fldQGBqpuv` | Manually entered description of actual received item |
| Status | `fld6Fri64S` | One of four exact form options |

Valid Status values: `Refunded (Seller Fault)`, `Dispute Approved`, `Dispute Rejected`, `In-Dispute`. The new workflow uses the single visible **Status** choice; it does not attempt to populate the hidden Dispute Results field.

## Routing

- **Wrong Item** / **Scam**: no Odoo ticket/TC-IN. File to the new Lark Base (one form per affected item).
- **Normal physically Returned**: existing Odoo workflow, then the original Lark Item Returns Base.
- **Normal Not Returned**: existing no-Odoo direct filing to the original Lark Base.
- **Mixed order**: one Odoo ticket for normal physically Returned items; special items separately file to Wrong Item / Scam Base. No special item is included in the Odoo stock-transfer item set.

## UI / history

- Added **Scam** to Classification.
- Added item-level **Received Item** and **Wrong Item / Scam Status** editor fields, shown for the two new classifications.
- Updated History editor and JSON persistence for these two fields; pre-transaction edits remain possible.
- Existing Restore, Archive, Delete Local Record, Manual Odoo / TC-IN, settings, and Odoo recovery remain in place.

## Duplicate prevention

- Normal and Wrong Item Lark submissions have distinct, durable result checkpoints.
- Each verified successful Lark form is recorded before the next form opens.
- On retry, previously saved records are skipped (route-key identity must match).
- Another scan with previously recorded Lark filing results for the same marketplace Order ID blocks fresh submission.
- Uncertain form-submit outcomes still require manual verification in Lark, since a browser cannot guarantee whether an unconfirmed response created a remote record.

## Testing / compatibility

- `main.py` based on v1.0.5-test; existing `odoo.py` from v1.0.5.3-test is unchanged.
- `lark.py` based on v1.0.4.8-test with additive optional per-record checkpoint callback/skip support.
- Python syntax and imports verified with current marketplace, theme, and Odoo modules.
- 12 offline tests passed, including mixed routing, Source-to-form fields, missing mandatory values, per-record history, recovery of partial submissions, and normal Lark retries.
- Headless Tkinter tests verified the compact editor and saved Scan History edits.
- No live authenticated Lark or Odoo transaction has been executed for this release.
