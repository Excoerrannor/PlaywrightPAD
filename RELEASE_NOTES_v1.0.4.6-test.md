# Makerlab Return Processor v1.0.4.6-test

**November 13, 2026 | Test release**  
**Base:** v1.0.4.5-test  
**Changed production files:** `tiktok.py`, `main.py`, `lark.py`.

## TikTok: multiple independent return cards for the same parent Order ID

Previously, Tracking Number search demanded exactly one distinct TikTok `reverse_main_order_id`. A valid marketplace order containing multiple independent return requests therefore raised the "did not produce a new, unambiguous return" error.

The parser now:

- Allows multiple return cards **only when all visible matching cards have one parent marketplace `main_order_id`**.
- Recognizes each distinct `reverse_main_order_id` without counting the companion header and details rows twice.
- Opens every return card's product-details dropdown, extracts Seller SKU and quantity, and validates each card independently.
- Reacquires each row by its stable Return Order ID after TikTok rerenders the page.
- Never returns a partial result if a card lacks SKU, quantity, refund or verifiable identity.
- Accepts the item-count badge when it represents the count of product rows or of total units, requiring all SKU/QTY details in either case.
- Continues to support searches by a single Return Order ID.
- Rejects a tracking search containing multiple unrelated parent orders or an apparently unchanged result set left from a different tracking number.

The normalized main application keeps `source_data.return_order_id` on each item and stores all return IDs and per-return refund/quantity totals in the saved case. Users can edit classification/decision/remarks for each row separately. Multiple cards with the same Seller SKU remain distinct items until the existing Odoo workflow groups them appropriately.

## Refund values and Lark safety

Each return card's own Refund is summed to the marketplace-order total. The repeated `Paid` amount displayed on each return card is **not** added repeatedly. For multiple returns, `value_mode=tiktok_return_groups` prevents reusing the entire order refund for each separate Lark transfer.

- When one Lark filing contains **all units of a TikTok return card**, it uses that card's verified refund.
- If a return card contains multiple SKU rows and those rows go to **different** Odoo transfers or direct Lark records, the operator must provide accurate per-item Amounts. A global preflight checks that the amounts sum to the card's refund **before any Lark filing**.
- Ordinary Shopee/Lazada and legacy single-return TikTok value logic are unchanged.

## Example in the user-provided TikTok HTML

Parent Order ID `586832186683459538` contained four return requests:

| Return Order ID | Item badge | Refund |
|---|---:|---:|
| `4042924017911957458` | 3 | PHP 657.00 |
| `4042924059127089106` | 2 | PHP 292.60 |
| `4042923981018859474` | 1 | PHP 764.10 |
| `4042924061758359506` | 1 | PHP 449.10 |
| **Total** | **7** | **PHP 2,162.80** |

The source HTML did not include open SKU product-popovers, so the actual SKU list is intentionally not asserted in these notes.

## Offline verification

- Real saved TikTok return-card DOM tested through headless Chromium (Playwright), with *synthetic* product-popovers because the uploaded HTML contained no open SKU details.
- Tracking Number resolves all four returns; Order ID resolves the same four; Return Order ID resolves a single return.
- Refuses stale unchanged result sets when another tracking number was searched and refuses mixed parent Order IDs.
- Parsed quantity and refund sum verified, with per-return metadata preserved into `main.py`.
- Lark value calculations verified across multiple cards, complete return groups and split groups.
- Lark global preflight rejects mismatched refunds before sending any Lark forms.
- `py_compile` and importing with the current main application dependencies verified.

**No live TikTok/Odoo/Lark changes were made.** Confirm the first production scan manually.
