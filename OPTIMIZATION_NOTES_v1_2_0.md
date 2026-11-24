# Makerlab Return Processor - Optimization Notes

## Scope
Optimized:
- main.py
- shopee.py
- odoo.py
- lark.py

Keep your existing browser_manager.py unchanged.

## Preserved workflow
- Shopee Order ID extraction, including ignoring optional Booking ID
- Returned SKU/QTY/unit-price extraction
- Editable item list with Add/Remove Item
- Duplicate SKU rows for separate handling
- One Odoo Helpdesk ticket per Shopee order
- Duplicate SKU quantities combined in ticket title
- Odoo return grouping by Decision + Classification + Status
- New -> MNL/Stock
- Unsealed -> QC Fail -> TC/Stock/Open Box
- Defective -> QC Fail -> TC/Defective
- Multi-SKU QC dialog handling
- One Lark filing per Odoo Transfer ID
- Shopee refund/order value used for Lark Value
- Not Returned -> skip Odoo -> direct Lark filing
- Not Returned -> Transfer ID / Transfer Link blank
- Not Returned -> Odoo Tag optional

## Main optimizations
- Centralized workflow constants and item defaults.
- Centralized button-state logic.
- One-call Treeview clearing instead of deleting rows one by one.
- Odoo Tag UI now follows Status and is optional for Not Returned.
- Reused item factory instead of duplicating item dictionaries.

## Shopee optimizations
- Precompiled regular expressions.
- Removed an unnecessary locator count round-trip in Order ID extraction.
- Kept returned-product extraction as a single browser-side evaluation.
- Reduced duplicate string parsing/cleanup code.

## Odoo optimizations
- Precompiled ticket / transfer / SKU regexes.
- Centralized return-table extraction.
- Replaced repeated full-table polling while waiting for SKUs with Playwright locator waits.
- Preserved exact-SKU data-tooltip safety matching.
- Preserved no Ctrl+A / Tab / Enter / coordinate-click quantity editing.
- Centralized progress and unique-tag handling.
- Simplified return grouping while preserving order.

## Lark optimizations
- Centralized record construction/submission.
- Removed duplicated Returned vs Not Returned submission code.
- Preserved quantity-aware duplicate-SKU matching.
- Preserved one filing per Transfer ID for Returned items.
- Preserved direct filing with blank transfer fields for Not Returned items.

## Verification performed
- All four files syntax-checked successfully.
- Shopee Booking ID parsing tested.
- Refund-value parsing tested.
- Duplicate SKU Odoo title/grouping tested.
- Duplicate SKU Lark transfer allocation tested.
- Not Returned + blank Odoo Tag editor validation tested.
- Returned + blank Odoo Tag correctly rejected.
- Not Returned direct Lark filing tested with blank Transfer ID/Link.
- Mixed Returned + Not Returned Lark flow tested.

## Important
Browser automation still depends on live Shopee/Odoo/Lark DOM behavior.
Before publishing a new EXE release, regression-test:
1. Single New returned item
2. Single Unsealed returned item
3. Single Defective returned item
4. Multi-SKU same classification
5. Same SKU split between Unsealed and Defective
6. Booking ID Shopee order
7. All Not Returned
8. Mixed Returned + Not Returned
9. Multiple Odoo Transfer IDs -> one Lark form per Transfer ID
