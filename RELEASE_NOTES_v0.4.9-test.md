Makerlab Return Processor v0.4.9-test

Highlights

This release expands the Makerlab Return Processor from Shopee-only processing into a multi-platform returns workflow supporting Shopee, Lazada, and TikTok Shop.

New Features

\- Added Lazada Returns support.

\- Added TikTok Shop Returns support.

\- Added barcode scanner-friendly Tracking Number search.

\- Barcode scanners that automatically send Enter can now immediately trigger searches.

\- Added search by:

&#x20; - Tracking Number

&#x20; - Order ID

&#x20; - Platform-specific identifiers where supported.

\- Added shared Odoo + Lark workflow across Shopee, Lazada, and TikTok.

Lazada Improvements

\- Search Lazada returns using Tracking Number.

\- Automatically switches Lazada search filter to Tracking Number.

\- Reads return information directly from the Lazada Return Orders page.

\- Supports multi-item Lazada returns.

\- Captures:

&#x20; - Order ID

&#x20; - Return Order ID

&#x20; - Seller SKU

&#x20; - Return Item ID

&#x20; - Order Item ID

&#x20; - Refund Amount

&#x20; - Return Reason

&#x20; - Tracking Number

&#x20; - Logistics Status

\- Handles intermittent Lazada logout.

\- Automatically clicks Log in when redirected to the registration page.

\- Automatically clicks the password Login button when saved browser credentials are already populated.

\- Does not store Lazada credentials in the application source.

TikTok Shop Improvements

\- Added TikTok Seller Center Manage Returns integration.

\- Tracking-number barcode workflow supported.

\- Added delayed keyboard input and Enter handling for more reliable TikTok searches.

\- Product details are now opened by clicking the item details instead of relying on hover.

\- Improved Seller SKU extraction.

\- Prevents adjacent labels such as Speedy refund from being included in SKU values.

\- Supports SKU and quantity extraction from TikTok return product details.

Shopee Improvements

\- Tracking-number search added to the Shopee Return/Refund list.

\- Processor uses the matching Order ID hyperlink to open the correct Shopee Order Details page.

\- Existing Shopee Order Link and Order ID workflows remain available.

Lark Filing Improvements

\- Improved Lark Item Returns form reliability.

\- New Lark form tabs are used to avoid stale form state.

\- Existing prefilled values are preserved.

\- Missing select values can be set directly by the processor.

\- Classification, Status, Decision, Platform, and Grade are verified before submission.

\- Lark completion is only considered successful after the form reaches the Submitted state.

\- If Odoo succeeds but Lark fails, the processor can retry Lark without recreating the Odoo transfer during the same session.

Interface Improvements

\- Order details are now selectable and copyable.

\- Added Copy All Case Details.

\- Returned-item rows can be copied.

\- Odoo/Lark results can be highlighted and copied.

\- Added a prominent Odoo Transfer ID field directly below the refund total.

\- Transfer IDs such as TC/IN/##### remain visible after Odoo processing and Lark retries.

\- Multiple transfer IDs are displayed when one return creates multiple Odoo transfers.

