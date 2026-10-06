import re
from urllib.parse import urljoin

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

_BOOKING_SUFFIX_RE = re.compile(
    r"\s*\(\s*Booking\s+ID\s*:[^)]*\)\s*",
    re.IGNORECASE,
)
_ORDER_TOKEN_RE = re.compile(r"^([A-Za-z0-9]+)")
_MONEY_CLEAN_RE = re.compile(r"[^\d.-]")


def _clean_text(value) -> str:
    return str(value or "").strip()


def _parse_refund_value(text: str) -> float:
    cleaned = _MONEY_CLEAN_RE.sub("", _clean_text(text).replace(",", ""))
    if not cleaned:
        raise ValueError(f"Could not parse refund amount from {text!r}")
    return float(cleaned)


def _extract_order_token(text: str) -> str:
    text = _BOOKING_SUFFIX_RE.sub("", _clean_text(text)).strip()
    match = _ORDER_TOKEN_RE.match(text)
    return match.group(1) if match else ""


def get_order_id(page) -> str:
    """
    Extract the real Shopee Order ID while ignoring an optional Booking ID.
    Regular-order behavior is unchanged.
    """
    element = page.get_by_test_id(ORDER_ID_TEST_ID)
    element.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    # Fast path: the .body contains the order value and optional booking suffix.
    try:
        order_id = _extract_order_token(
            element.locator(".body").first.inner_text(timeout=2_000)
        )
        if order_id:
            return order_id
    except Exception:
        pass

    # Defensive fallback for alternate Shopee layouts.
    full_text = _clean_text(element.inner_text())
    for line in map(str.strip, full_text.splitlines()):
        if not line:
            continue
        lowered = line.lower()
        if lowered == "order id" or "booking id" in lowered:
            continue
        order_id = _extract_order_token(line)
        if order_id:
            return order_id

    raise ValueError(f"Could not extract Shopee Order ID from {full_text!r}")


def get_returned_products(page) -> list[dict]:
    """
    Return SKU, returned quantity, unit price, and amount for each returned row.
    Extraction is intentionally done in one browser-side pass.
    """
    payment = page.get_by_test_id(ORDER_PAYMENT_TEST_ID)
    payment.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    payment.locator(PRODUCT_ROW_SELECTOR).first.wait_for(
        state="attached",
        timeout=DEFAULT_TIMEOUT,
    )

    returned_rows = payment.locator(RETURNED_ROW_SELECTOR)
    try:
        returned_rows.first.wait_for(
            state="attached",
            timeout=RETURN_MARKER_TIMEOUT,
        )
    except Exception:
        return []

    return returned_rows.evaluate_all(
        """
        rows => rows.map(row => {
            const skuText =
                row.querySelector("div.product-meta > div:last-child")
                    ?.textContent?.trim() || "";
            const returnText =
                row.querySelector("label.return-label")
                    ?.textContent?.trim() || "";
            const priceText =
                row.querySelector(":scope > div.price")
                    ?.textContent?.trim() || "";

            const sku = skuText.match(/MLE\\d+/)?.[0] || "";
            const quantity = Number(returnText.match(/^\\s*(\\d+)/)?.[1] || NaN);
            const unitPrice = Number(
                priceText.replace(/,/g, "").replace(/[^0-9.-]/g, "")
            );

            if (!sku || !Number.isFinite(quantity) || !Number.isFinite(unitPrice)) {
                return null;
            }

            return {
                sku,
                quantity,
                unit_price: unitPrice,
                amount: Number((unitPrice * quantity).toFixed(2))
            };
        }).filter(Boolean)
        """
    )


def get_return_case_data(page, order_id: str) -> dict:
    """
    Search the Shopee Return/Refund list by Order ID and return the matching
    Request ID, total customer refund, and return-detail link.
    """
    order_id = _clean_text(order_id)
    if not order_id:
        raise ValueError("Order ID is empty.")

    panel = page.locator(".advance-filter-container")
    panel.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)

    search = panel.locator(
        f'input[placeholder="{RETURN_SEARCH_PLACEHOLDER}"]'
    )
    search.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    search.fill(order_id)

    panel.get_by_role("button", name="Apply", exact=True).click()

    row = page.locator(RETURN_ROW_SELECTOR).filter(has_text=order_id).first
    row.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)

    data = row.evaluate(
        """
        row => {
            const text = selector =>
                row.querySelector(selector)?.textContent?.trim() || "";
            return {
                order_id: text(".order-id .id-content"),
                request_id: text(".return-id .id-content"),
                refund_text: text(".item-refund-amount .amount-content"),
                return_href: row.getAttribute("href") || ""
            };
        }
        """
    )

    found_order_id = _clean_text(data.get("order_id"))
    if found_order_id != order_id:
        raise ValueError(
            "Wrong Shopee return record found. "
            f"Expected {order_id}, got {found_order_id}"
        )

    refund_text = _clean_text(data.get("refund_text"))
    if not refund_text:
        raise ValueError(
            f"Refund amount was not found for Order ID {order_id}."
        )

    return_href = _clean_text(data.get("return_href"))
    return {
        "order_id": found_order_id,
        "request_id": _clean_text(data.get("request_id")),
        "refund_text": refund_text,
        "refund_value": _parse_refund_value(refund_text),
        "return_href": return_href,
        "return_url": urljoin(page.url, return_href) if return_href else "",
    }


__all__ = [
    "get_order_id",
    "get_returned_products",
    "get_return_case_data",
]
