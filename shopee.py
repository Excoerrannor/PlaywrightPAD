import re
from urllib.parse import urljoin

# =============================================================
# SHOPEE SELECTORS / TIMEOUTS
# =============================================================

DEFAULT_TIMEOUT = 30_000
RETURN_MARKER_TIMEOUT = 12_000

ORDER_ID_TEST_ID = "odp-label-order-id"
ORDER_PAYMENT_TEST_ID = "odp-order-payment"

PRODUCT_ROW_SELECTOR = "div.product-list-item:not(.product-list-head)"
RETURNED_ROW_SELECTOR = "div.product-list-item:has(label.return-label)"

RETURN_SEARCH_PLACEHOLDER = (
    "Input Request ID Order ID Return Tracking Number Buyer Name"
)

RETURN_ROW_SELECTOR = "a.return-row-item"


# =============================================================
# SMALL HELPERS
# =============================================================

def _parse_refund_value(text: str) -> float:
    """
    Convert values such as:
        ₱879.00
        ₱1,143.00
    into:
        879.0
        1143.0
    """

    cleaned = re.sub(
        r"[^\d.]",
        "",
        text.replace(",", "")
    )

    if not cleaned:
        raise ValueError(
            f"Could not parse refund amount from {text!r}"
        )

    return float(cleaned)


# =============================================================
# ORDER PAGE
# =============================================================

def get_order_id(page) -> str:
    """
    Extract ONLY the actual Shopee Order ID from an Order Details page.

    Regular order:
        Order ID
        260822184N9XJB

    Advance-booking order:
        Order ID
        2609020K9YKJ9H
        (Booking ID: 260831AASREZS5CLKRU)

    The Booking ID is intentionally ignored.
    """

    element = page.get_by_test_id(
        ORDER_ID_TEST_ID
    )

    element.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    # Prefer the Order ID card's body so the "Order ID" heading itself
    # is not mixed into the value.
    body = element.locator(
        ".body"
    ).first

    if body.count() > 0:
        body_text = body.inner_text().strip()

        # Advance-booking orders append:
        #   (Booking ID: XXXXXXXXX)
        # Remove only that optional suffix. Regular orders are unchanged.
        order_text = re.sub(
            r"\s*\(\s*Booking\s+ID\s*:[^)]*\)\s*",
            "",
            body_text,
            flags=re.IGNORECASE,
        ).strip()

        # The actual Order ID is the first non-space value remaining.
        match = re.match(
            r"^([A-Za-z0-9]+)",
            order_text,
        )

        if match:
            return match.group(1)

    # Fallback for future/alternate Shopee layouts:
    # inspect the whole card, but explicitly exclude the heading and
    # any Booking ID line.
    full_text = element.inner_text().strip()

    lines = [
        line.strip()
        for line in full_text.splitlines()
        if line.strip()
    ]

    candidates = [
        line
        for line in lines
        if line.lower() != "order id"
        and "booking id" not in line.lower()
    ]

    for candidate in candidates:
        match = re.match(
            r"^([A-Za-z0-9]+)",
            candidate,
        )

        if match:
            return match.group(1)

    raise ValueError(
        f"Could not extract Shopee Order ID from {full_text!r}"
    )



def get_returned_products(page) -> list[dict]:
    """
    Extract all returned products from the Shopee Order page.

    Output:
        [
            {
                "sku": "MLE08858",
                "quantity": 1,
                "unit_price": 1099.00,
                "amount": 1099.00
            },
        ]

    amount = unit_price * returned quantity

    This implementation minimizes Playwright round-trips by extracting
    all returned rows in one browser-side evaluation.
    """

    payment = page.get_by_test_id(
        ORDER_PAYMENT_TEST_ID
    )

    payment.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT
    )

    # Wait for Shopee's asynchronously rendered product list.
    product_rows = payment.locator(
        PRODUCT_ROW_SELECTOR
    )

    product_rows.first.wait_for(
        state="attached",
        timeout=DEFAULT_TIMEOUT
    )

    returned_rows = payment.locator(
        RETURNED_ROW_SELECTOR
    )

    # Returned markers can appear slightly after the product rows.
    try:
        returned_rows.first.wait_for(
            state="attached",
            timeout=RETURN_MARKER_TIMEOUT
        )
    except Exception:
        return []

    # One Playwright call extracts SKU, returned QTY, Unit Price,
    # and computes the per-item return amount.
    products = returned_rows.evaluate_all(
        """
        rows => rows.map(row => {
            const skuNode = row.querySelector(
                "div.product-meta > div:last-child"
            );

            const returnNode = row.querySelector(
                "label.return-label"
            );

            // This .price column is the Unit Price for this product row.
            const priceNode = row.querySelector(
                ":scope > div.price"
            );

            const skuText = skuNode?.textContent?.trim() || "";
            const returnText = returnNode?.textContent?.trim() || "";
            const priceText = priceNode?.textContent?.trim() || "";

            const skuMatch = skuText.match(/MLE\\d+/);
            const qtyMatch = returnText.match(/^\\s*(\\d+)/);

            const normalizedPrice = priceText
                .replace(/,/g, "")
                .replace(/[^0-9.-]/g, "");

            const unitPrice = Number(normalizedPrice);

            if (
                !skuMatch ||
                !qtyMatch ||
                !Number.isFinite(unitPrice)
            ) {
                return null;
            }

            const quantity = Number(qtyMatch[1]);

            return {
                sku: skuMatch[0],
                quantity: quantity,
                unit_price: unitPrice,
                amount: Number(
                    (unitPrice * quantity).toFixed(2)
                )
            };
        }).filter(Boolean)
        """
    )

    return products


# =============================================================
# RETURN / REFUND LIST PAGE
# =============================================================

def get_return_case_data(page, order_id: str) -> dict:
    """
    Search the Shopee Return/Refund list by Order ID and return:

        {
            "order_id": "...",
            "request_id": "...",
            "refund_text": "₱879.00",
            "refund_value": 879.0,
            "return_href": "/portal/sale/return/...",
            "return_url": "https://seller.shopee.ph/portal/sale/return/..."
        }

    The search field is used first so Playwright only needs to inspect
    the matching result instead of scanning the entire return list.
    """

    order_id = order_id.strip()

    if not order_id:
        raise ValueError(
            "Order ID is empty."
        )

    # Scope the controls to Shopee's advanced-filter area so we don't
    # accidentally click another Apply button elsewhere on the page.
    filter_panel = page.locator(
        ".advance-filter-container"
    )

    filter_panel.wait_for(
        state="attached",
        timeout=DEFAULT_TIMEOUT
    )

    search_input = filter_panel.locator(
        f'input[placeholder="{RETURN_SEARCH_PLACEHOLDER}"]'
    )

    search_input.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT
    )

    # fill() replaces the previous Order ID automatically.
    search_input.fill(
        order_id
    )

    apply_button = filter_panel.get_by_role(
        "button",
        name="Apply",
        exact=True
    )

    apply_button.click()

    # Wait directly for the matching row. No fixed sleep is required.
    matching_row = page.locator(
        RETURN_ROW_SELECTOR
    ).filter(
        has_text=order_id
    ).first

    matching_row.wait_for(
        state="attached",
        timeout=DEFAULT_TIMEOUT
    )

    # Extract everything from the row in a single browser round-trip.
    data = matching_row.evaluate(
        """
        row => {
            const text = selector =>
                row.querySelector(selector)?.textContent?.trim() || "";

            return {
                order_id: text(".order-id .id-content"),
                request_id: text(".return-id .id-content"),
                refund_text: text(
                    ".item-refund-amount .amount-content"
                ),
                return_href: row.getAttribute("href") || ""
            };
        }
        """
    )

    found_order_id = data["order_id"]

    if found_order_id != order_id:
        raise ValueError(
            "Wrong Shopee return record found. "
            f"Expected {order_id}, got {found_order_id}"
        )

    refund_text = data["refund_text"]

    if not refund_text:
        raise ValueError(
            f"Refund amount was not found for Order ID {order_id}."
        )

    return_href = data["return_href"]

    return {
        "order_id": found_order_id,
        "request_id": data["request_id"],
        "refund_text": refund_text,
        "refund_value": _parse_refund_value(
            refund_text
        ),
        "return_href": return_href,
        "return_url": (
            urljoin(page.url, return_href)
            if return_href
            else ""
        ),
    }


__all__ = [
    "get_order_id",
    "get_returned_products",
    "get_return_case_data",
]
