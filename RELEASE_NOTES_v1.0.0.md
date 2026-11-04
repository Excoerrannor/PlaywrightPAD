# Makerlab Return Processor v1.0.0

## Overview
First v1.0.0 release of the Windows returns processor for Shopee, Lazada, and TikTok Shop, with Odoo and Lark workflow integration.

## Key features
- Marketplace tracking-number and order search, barcode-friendly.
- Lazada repeated-SKU consolidation: one row per SKU with combined quantity and refund total; original Return Item IDs retained.
- TikTok SKU and quantity parsing fixes, including dimension-text protection and multi-quantity validation.
- Odoo ticket and stock-return processing with inventory-pending checkpoints.
- Persistent JSON scan history and recovery checkpoints across restarts.
- Searchable History and Recovery window, with selective restore of eligible pending cases.
- Lark form verification and retry using existing Odoo results.
- Copyable details, highlighted Odoo Transfer IDs, rounded responsive desktop interface and button hover colors.

## Operator notes
- Review order, SKU, quantity, amount, classification, decision and status before submission.
- Mixed-condition units should not be combined under a single handling decision.
- Manually check Odoo before resuming any case where transfer creation status is uncertain.
- Marketplace sessions, verification and page layouts may require operator attention.
- Local data/ JSON files and Chrome browser profile must not be included in public GitHub artifacts.
- A compiled ZIP may rely on Google Chrome and the locally configured persistent browser profile path.

## Release status
Tag v1.0.0 after checking the latest source and testing the Windows build. Live end-to-end production acceptance should be completed before declaring this build fully production-approved.
