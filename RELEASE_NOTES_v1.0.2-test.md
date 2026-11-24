# Makerlab Return Processor v1.0.2-test

## Odoo ticket and return recovery

- Persist a recovery snapshot immediately after a new Helpdesk ticket URL is confirmed, **before** selecting Product, Tags, or Priority.
- Persist a manual-review marker immediately **before** creating a ticket, to protect against crashes during Add.
- Resume failed product selection on the **same ticket**, rather than creating another ticket.
- Keep the exact Order ID, marketplace, ticket title/URL, SKUs, confirmed item decisions, and Odoo progress in local JSON.
- Save a manual-review-only safety marker just before creating an Odoo stock return; do not retry an unknown TC/IN outcome automatically.
- Save each completed and validated TC/IN independently; skip completed return groups when resuming.
- Persist completed Odoo results before Lark filing so Lark failures can be retried without recreating Odoo work.
- Detect an existing Odoo case for a rescanned Order ID in either Recovery or completed Scan History, and block accidental duplicate ticket submission.
- Show new checkpoint stages in the History/Recovery table.
- Preserve the November 2026 Odoo product dropdown SKU matching fix.

## Unchanged

Shopee, Lazada (including grouped SKU quantities), TikTok, Lark, browser profile, JSON file format, and rounded/glass UI styling remain unchanged.

## Important

**Test release.** Run a controlled validation in Odoo before production use. Older Odoo tickets that were created before this version are not automatically added to recovery. If Odoo may have created a transfer but did not report its status, manually inspect Odoo before proceeding.
