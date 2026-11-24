\# Makerlab Return Processor v0.4.10-test



\## Highlights



This release improves TikTok Shop return processing and includes all fixes and improvements introduced through v0.4.9-test.



\## TikTok Shop Fixes



\- Fixed incorrect quantity detection from product variant text.

\- Product variants containing dimensions such as `200x200x80` are no longer interpreted as return quantities.

\- Quantity is now extracted specifically from TikTok's dedicated quantity element such as `× 1`.

\- Improved Seller SKU extraction to prevent adjacent labels such as `Speedy refund` from being included in the SKU.

\- Preserved delayed keyboard entry and Enter behavior for more reliable TikTok tracking-number searches.

\- Preserved click-to-open product details behavior.



\## Lazada Improvements



\- Supports tracking-number searches.

\- Automatically switches the Lazada search mode to Tracking Number.

\- Handles intermittent Lazada login requirements.

\- Automatically clicks the initial `Log in` link when Lazada redirects to the registration page.

\- Switches to the newly opened login tab.

\- Clicks `Login` when Chrome has already populated the saved credentials.

\- Does not store Lazada login credentials in the source code.



\## Lark Improvements



\- Improved handling of prefilled Lark forms.

\- Classification, Status, Decision, Platform, and Grade are verified before submission.

\- Existing prefilled values are preserved when correctly loaded.

\- Fresh Lark tabs help prevent stale form state.

\- Odoo results can be reused during a Lark retry within the same processor session.



\## Interface Improvements



\- Order details and processing results can be highlighted and copied.

\- Added Copy All Case Details.

\- Added copy support for returned-item rows.

\- Odoo Transfer IDs are displayed prominently below the refund amount.

\- Transfer IDs such as `TC/IN/#####` remain visible after processing.



\## Supported Platforms



\- Shopee

\- Lazada

\- TikTok Shop



\## Important Notes



This is still a test/pre-release version.



Always verify:

\- Order ID

\- SKU

\- Quantity

\- Refund amount

\- Classification

\- Status

\- Decision



before final submission to Odoo and Lark.

