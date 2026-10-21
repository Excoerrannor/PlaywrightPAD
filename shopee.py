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


def _normalized_token(value) -> str:
    return re.sub(r"\s+", "", _clean_text(value)).upper()


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
    """Extract the real Shopee Order ID while ignoring an optional Booking ID."""
    element = page.get_by_test_id(ORDER_ID_TEST_ID)
    element.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    try:
        order_id = _extract_order_token(
            element.locator(".body").first.inner_text(timeout=2_000)
        )
        if order_id:
            return order_id
    except Exception:
        pass

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
    """Return SKU, returned quantity, unit price, and amount for each return row."""
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
            const productName =
                row.querySelector(".product-name")?.textContent?.trim() ||
                row.querySelector(".product-info .name")?.textContent?.trim() ||
                "";

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
                amount: Number((unitPrice * quantity).toFixed(2)),
                product_name: productName
            };
        }).filter(Boolean)
        """
    )


def _search_return_case(
    page,
    query: str,
    *,
    expected_order_id: str = "",
    expected_tracking: str = "",
) -> dict:
    """
    Search Shopee's single Return/Refund search box.

    Shopee accepts Order ID and Return Tracking Number in the same field, so no
    search-filter dropdown change is required for barcode scanning.
    """
    query = _clean_text(query)
    if not query:
        raise ValueError("Shopee return search value is empty.")

    panel = page.locator(".advance-filter-container")
    panel.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)

    search = panel.locator(
        f'input[placeholder="{RETURN_SEARCH_PLACEHOLDER}"]'
    )
    search.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    search.fill(query)

    panel.get_by_role("button", name="Apply", exact=True).click()

    row = page.locator(RETURN_ROW_SELECTOR).filter(has_text=query).first
    try:
        row.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    except Exception as error:
        label = "Tracking Number" if expected_tracking else "Order ID"
        raise ValueError(
            f"Shopee return was not found for {label}: {query}"
        ) from error

    data = row.evaluate(
        """
        row => {
            const text = selector =>
                row.querySelector(selector)?.textContent?.trim() || "";
            const productNames = [...row.querySelectorAll(".ct-item-product-name")]
                .map(node => node.textContent?.trim() || "")
                .filter(Boolean);
            const trackingNumbers = [...row.querySelectorAll(
                ".item-return-logistic .tracking-number, .tracking-number"
            )]
                .map(node => node.textContent?.trim() || "")
                .filter(Boolean);
            return {
                order_id: text(".order-id .id-content"),
                request_id: text(".return-id .id-content"),
                refund_text: text(".item-refund-amount .amount-content"),
                tracking_numbers: [...new Set(trackingNumbers)],
                source_href: row.getAttribute("href") || "",
                product_names: productNames
            };
        }
        """
    )

    found_order_id = _clean_text(data.get("order_id"))
    tracking_numbers = [
        _clean_text(value)
        for value in (data.get("tracking_numbers") or [])
        if _clean_text(value)
    ]
    tracking_number = tracking_numbers[0] if tracking_numbers else ""

    if expected_order_id and found_order_id != _clean_text(expected_order_id):
        raise ValueError(
            "Wrong Shopee return record found. "
            f"Expected Order ID {expected_order_id}, got {found_order_id or 'blank'}"
        )

    if expected_tracking:
        wanted_tracking = _normalized_token(expected_tracking)
        matched_tracking = next(
            (
                value for value in tracking_numbers
                if _normalized_token(value) == wanted_tracking
            ),
            "",
        )
        if not matched_tracking:
            raise ValueError(
                "Wrong Shopee return record found. "
                f"Expected Tracking Number {expected_tracking}, got "
                f"{', '.join(tracking_numbers) or 'blank'}"
            )
        tracking_number = matched_tracking

    refund_text = _clean_text(data.get("refund_text"))
    if not refund_text:
        raise ValueError(
            f"Refund amount was not found for Shopee Order ID {found_order_id or query}."
        )

    source_href = _clean_text(data.get("source_href"))
    source_url = urljoin(page.url, source_href) if source_href else ""
    if not source_url:
        raise ValueError(
            "Shopee search result did not provide a usable result link."
        )
    order_url = source_url if "/portal/sale/order/" in source_url else ""

    return {
        "order_id": found_order_id,
        "request_id": _clean_text(data.get("request_id")),
        "refund_text": refund_text,
        "refund_value": _parse_refund_value(refund_text),
        "tracking_number": tracking_number,
        "tracking_numbers": tracking_numbers,
        "source_href": source_href,
        "source_url": source_url,
        "order_href": source_href if order_url else "",
        "order_url": order_url,
        # Compatibility aliases used by older processor versions.
        "return_href": source_href,
        "return_url": source_url,
        "product_names": data.get("product_names") or [],
        "search_query": query,
        "search_by": "Tracking Number" if expected_tracking else "Order ID",
        "platform": "Shopee",
    }


def get_return_case_data(page, order_id: str) -> dict:
    """Search the Shopee Return/Refund list by visible Order ID."""
    return _search_return_case(
        page,
        order_id,
        expected_order_id=order_id,
    )


def get_return_case_by_tracking(page, tracking_number: str) -> dict:
    """Search Shopee Return/Refund by return-waybill Tracking Number."""
    return _search_return_case(
        page,
        tracking_number,
        expected_tracking=tracking_number,
    )


def open_order_from_return_row(page, order_id: str):
    """
    Click the visible Shopee Order ID inside the matched Return/Refund row.

    Shopee renders the Order ID as ``.order-id .id-content`` inside the
    clickable return row. Clicking this exact element mirrors the user's
    normal workflow and lets Seller Center decide the correct Order Details
    destination instead of constructing/navigating a URL ourselves.
    """
    order_id = _clean_text(order_id)
    if not order_id:
        raise ValueError("Shopee Order ID is empty.")

    row = page.locator(RETURN_ROW_SELECTOR).filter(has_text=order_id).first
    row.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    order_id_link = row.locator(".order-id .id-content").first
    order_id_link.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    visible_order_id = _clean_text(order_id_link.inner_text())
    if visible_order_id != order_id:
        raise ValueError(
            "Shopee Order ID safety check failed. "
            f"Expected {order_id}, found {visible_order_id or 'blank'}."
        )

    # The current Return List markup wraps the Order ID span in an anchor with
    # target="_blank". Handle both new-tab and same-tab variants so a minor
    # Shopee markup change does not break barcode processing.
    parent_link = order_id_link.locator("xpath=ancestor::a[1]")
    opens_new_tab = False
    try:
        opens_new_tab = (
            _clean_text(parent_link.get_attribute("target")) == "_blank"
        )
    except Exception:
        pass

    if opens_new_tab:
        with page.context.expect_page(timeout=DEFAULT_TIMEOUT) as new_page_info:
            order_id_link.click()
        order_page = new_page_info.value
        order_page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_TIMEOUT)
    else:
        order_id_link.click()
        page.wait_for_url("**/portal/sale/order/**", timeout=DEFAULT_TIMEOUT)
        order_page = page

    order_page.bring_to_front()
    return order_page


__all__ = [
    "get_order_id",
    "get_returned_products",
    "get_return_case_data",
    "get_return_case_by_tracking",
    "open_order_from_return_row",
]
