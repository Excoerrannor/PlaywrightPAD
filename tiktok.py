import json
import re

DEFAULT_TIMEOUT = 30_000
SEARCH_READY_TIMEOUT = 12_000
SEARCH_RESULT_TIMEOUT = 30_000
POPOVER_TIMEOUT = 8_000
PRODUCT_DETAILS_TIMEOUT = 6_000
SEARCH_KEYBOARD_SETTLE_MS = 1_200
SEARCH_KEYSTROKE_DELAY_MS = 45
SEARCH_ENTER_HOLD_MS = 120

SEARCH_INPUT_SELECTOR = (
    'input[data-tid="m4b_input_search"]'
    '[placeholder*="return tracking number"]'
)
RESULT_DATA_ROW_SELECTOR = (
    'tr[data-log_module_name="reverse_order_list_item"]'
    ':has([data-ele_text_name="reason_name_content"])'
)
VALID_SEARCH_MODES = {"Tracking Number", "Order ID", "Return Order ID"}

_MONEY_CLEAN_RE = re.compile(r"[^\d.-]")


def _text(value) -> str:
    return str(value or "").strip()


def _parse_money(text: str) -> float:
    cleaned = _MONEY_CLEAN_RE.sub("", _text(text).replace(",", ""))
    if not cleaned:
        return 0.0
    return float(cleaned)


def _wait_until_ready(page):
    """Require an authenticated TikTok Seller Center Manage returns page."""
    try:
        page.locator(SEARCH_INPUT_SELECTOR).wait_for(
            state="visible",
            timeout=SEARCH_READY_TIMEOUT,
        )
    except Exception as error:
        raise RuntimeError(
            "TikTok Seller Center Manage returns is not ready. TikTok must be "
            "logged in. Complete the TikTok login/verification in the processor "
            "Chrome window, then scan/search again."
        ) from error


def _row_meta(row) -> dict:
    raw = _text(row.get_attribute("data-log_json"))
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _result_identities(rows) -> list[dict]:
    identities = []
    for index in range(rows.count()):
        row = rows.nth(index)
        try:
            if not row.is_visible():
                continue
        except Exception:
            pass
        meta = _row_meta(row)
        if not meta:
            continue
        identities.append({
            "index": index,
            "order_id": _text(meta.get("main_order_id")),
            "return_order_id": _text(meta.get("reverse_main_order_id")),
        })
    return identities


def _find_result_row(
    page,
    query: str,
    search_by: str,
    *,
    previous_return_ids: set[str] | None = None,
    query_changed: bool = False,
):
    """
    Wait for TikTok's filtered result and return the data row.

    Order ID / Return Order ID can be verified directly from data-log_json.
    Tracking Number is not rendered in the overview row, so the safe condition
    is that TikTok has filtered the list to one distinct return order.
    """
    rows = page.locator(RESULT_DATA_ROW_SELECTOR)
    deadline_ms = SEARCH_RESULT_TIMEOUT
    step_ms = 250
    elapsed = 0

    while elapsed < deadline_ms:
        count = rows.count()
        if count:
            identities = _result_identities(rows)

            if search_by == "Order ID":
                for identity in identities:
                    if identity["order_id"] == query:
                        return rows.nth(identity["index"])

            elif search_by == "Return Order ID":
                for identity in identities:
                    if identity["return_order_id"] == query:
                        return rows.nth(identity["index"])

            else:
                distinct = {
                    item["return_order_id"]
                    for item in identities
                    if item["return_order_id"]
                }
                # One return order can have a header row + data row, but this
                # selector only includes the data row. Requiring one distinct
                # return order prevents loading an unfiltered list accidentally.
                if len(distinct) == 1:
                    # A different barcode must not reuse a previous one-result
                    # row: that can file the wrong return. Fail closed.
                    # barcode, do not accept the old single result while the
                    # SPA is still refreshing.
                    if (
                        query_changed
                        and previous_return_ids
                        and distinct == previous_return_ids
                                            ):
                        page.wait_for_timeout(step_ms)
                        elapsed += step_ms
                        continue

                    target = next(iter(distinct))
                    for identity in identities:
                        if identity["return_order_id"] == target:
                            return rows.nth(identity["index"])

        page.wait_for_timeout(step_ms)
        elapsed += step_ms

    if search_by == "Tracking Number":
        raise ValueError(
            "TikTok did not produce a new, unambiguous return after pressing Enter to "
            f"Search for Tracking Number {query}. If a previous result remains "
            "on screen, do not process it; retry the scan or search by Order ID."
        )
    raise ValueError(
        f"TikTok return was not found for {search_by}: {query}."
    )


def _extract_row_data(row) -> dict:
    """Extract stable, rendered fields from one TikTok return overview row."""
    data = row.evaluate(
        r"""
        row => {
            const clean = value => (value || "").replace(/\s+/g, " ").trim();
            const named = name => clean(
                row.querySelector(`[data-ele_text_name="${name}"]`)?.textContent
            );
            let meta = {};
            try {
                meta = JSON.parse(row.getAttribute("data-log_json") || "{}");
            } catch (_) {}

            return {
                order_id: clean(meta.main_order_id),
                return_order_id: clean(meta.reverse_main_order_id),
                reverse_type: clean(meta.reverse_type),
                return_reason: named("reason_name_content"),
                item_count_text: named("product_title"),
                paid_text: named("product_paid_content"),
                source_status: named("status_description"),
                logistics_title: named("fulfillment_return_title"),
                logistics_status: named("fulfillment_return_button_text"),
                logistics_time: named("fulfillment_return_time"),
                refund_text: named("amount_refund_content")
            };
        }
        """
    )
    data["refund_value"] = _parse_money(data.get("refund_text"))
    data["paid_value"] = _parse_money(data.get("paid_text"))
    return data


def _visible_product_popover(page):
    return page.locator(
        '.core-popover-content[role="tooltip"]:visible'
    ).last


def _open_product_details(page, row):
    """CLICK the row's item-count / dropdown to expose product details.

    TikTok's '1 item' control contains the down-chevron. It is not a
    read-only hover target: the details need an explicit click. We never
    click parcel acceptance, appeals, or other return-state actions.
    """
    trigger = row.locator(
        '[data-log_module_name="reverse_product_info"] '
        '[data-ele_text_name="product_title"]'
    ).first
    trigger.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    # Dismiss a previous item's details before selecting this row.
    old_popover = _visible_product_popover(page)
    if old_popover.count() and old_popover.is_visible():
        page.keyboard.press("Escape")

    # Click the actual item-count text first, then its chevron container
    # only if the first target did not open a product popover.
    attempts = [
        trigger,
        row.locator('[data-log_module_name="reverse_product_info"]').first,
    ]
    for candidate in attempts:
        try:
            candidate.click(timeout=PRODUCT_DETAILS_TIMEOUT)
            popover = _visible_product_popover(page)
            popover.wait_for(
                state="visible",
                timeout=PRODUCT_DETAILS_TIMEOUT,
            )
            popover.get_by_text(
                re.compile(r"Seller\s+SKU\s*:", re.IGNORECASE)
            ).first.wait_for(state="visible", timeout=POPOVER_TIMEOUT)
            return popover
        except Exception:
            continue

    raise RuntimeError(
        "TikTok item details did not open after CLICKING the item-count "
        "dropdown. Open the TikTok return manually and confirm its Seller "
        "SKU / QTY; do not Submit an unverified return."
    )


def _extract_products_from_popover(popover) -> list[dict]:
    """
    Parse Seller SKU and QTY from TikTok's product popover.

    The popover places each product inside a data-relative container and shows
    text such as `Seller SKU: MLE05124` plus `× 1` beside that product.
    """
    products = popover.evaluate(
        r"""
        popover => {
            const clean = value => (value || "").replace(/\s+/g, " ").trim();
            const containers = [...popover.querySelectorAll('div[data-relative="true"]')]
                .filter(node => /Seller\s+SKU\s*:/i.test(clean(node.textContent)));

            const result = [];
            for (const container of containers) {
                // Never read SKU from the entire product container.
                // textContent joins adjacent elements without a delimiter:
                // "Seller SKU: MLE05124" + "Speedy refund" becomes
                // "Seller SKU: MLE05124Speedy refund".
                const full = clean(container.textContent);
                const lineNodes = [...container.querySelectorAll(
                    '.line-clamp-2.w-full.whitespace-normal.break-word'
                )];
                const skuLine = lineNodes.find(node =>
                    /^Seller\s+SKU\s*:/i.test(clean(node.textContent))
                );
                if (!skuLine) continue;

                const skuText = clean(skuLine.textContent).replace(
                    /^Seller\s+SKU\s*:\s*/i, ""
                );
                // Local MLE codes consist of a numeric SKU and may contain
                // multiple '+'-joined MLE codes. Bound the match to the codes
                // so promotional badges can never be added to the SKU.
                const skuMatch = skuText.match(/^MLE\d+(?:\+MLE\d+)*/i);
                const sku = skuMatch ? skuMatch[0] : skuText.split(/\s+/)[0];
                if (!sku) continue;

                // Quantity is the dedicated direct sibling shown as `× 1`.
                // Do NOT search the full product text for "x<number>" because
                // variant names such as "RA 200x200x80 IP65" would incorrectly
                // be parsed as a quantity of 200.
                const qtyNode = [...container.children].find(node =>
                    /^×\s*\d+$/.test(clean(node.textContent))
                );
                const qtyText = clean(qtyNode?.textContent);
                const qtyMatch = qtyText.match(/^×\s*(\d+)$/);
                const quantity = Number(qtyMatch?.[1] || 1);
                let productName = "";
                for (const node of lineNodes) {
                    const value = clean(node.textContent);
                    if (!value || /^Seller\s+SKU\s*:/i.test(value)) continue;
                    productName = value;
                    break;
                }

                result.push({
                    sku: sku.toUpperCase(),
                    quantity: Number.isFinite(quantity) && quantity > 0
                        ? quantity
                        : 1,
                    product_name: productName,
                    raw_text: full
                });
            }
            return result;
        }
        """
    )

    normalized = []
    for product in products or []:
        sku = _text(product.get("sku")).upper()
        if not sku:
            continue
        try:
            quantity = int(product.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1
        normalized.append({
            "sku": sku,
            "quantity": max(quantity, 1),
            "product_name": _text(product.get("product_name")),
            "raw_text": _text(product.get("raw_text")),
        })
    return normalized


def get_tiktok_return_order(
    page,
    query: str,
    *,
    search_by: str = "Tracking Number",
) -> dict:
    """
    Search TikTok Manage returns by tracking number, Order ID, or Return Order ID.

    TikTok's single search field supports all three identifiers. The desktop
    app receives the scanner's Enter, then types the scanned value into Seller
    Center and sends a separate, delayed Enter while that input has focus.
    """
    query = _text(query)
    search_by = _text(search_by) or "Tracking Number"

    if not query:
        raise ValueError(f"TikTok {search_by} is empty.")
    if search_by not in VALID_SEARCH_MODES:
        raise ValueError(f"Unsupported TikTok search mode: {search_by}")

    _wait_until_ready(page)

    search = page.locator(SEARCH_INPUT_SELECTOR)
    previous_query = _text(search.input_value())
    existing_rows = page.locator(RESULT_DATA_ROW_SELECTOR)
    previous_return_ids = {
        item["return_order_id"]
        for item in _result_identities(existing_rows)
        if item["return_order_id"]
    }

    # React-controlled searches can read stale input state if fill() and Enter
    # arrive back-to-back. Simulate real key events, then allow the input's
    # debounce/state update to finish before submitting the search.
    search.click()
    search.fill("")
    search.press_sequentially(query, delay=SEARCH_KEYSTROKE_DELAY_MS)
    if _text(search.input_value()) != query:
        raise RuntimeError(
            "TikTok tracking/order search input did not retain the scanned value."
        )

    print(
        f"TIKTOK SEARCH: typed {search_by} {query}; "
        f"waiting {SEARCH_KEYBOARD_SETTLE_MS}ms before Enter..."
    )
    page.wait_for_timeout(SEARCH_KEYBOARD_SETTLE_MS)

    # Focus the Seller Center input again, and send the Enter key from the
    # browser keyboard (separate from the scanner's Enter in the Tkinter GUI).
    # Do not switch to clicking the magnifying glass.
    try:
        search.focus()
        page.keyboard.press("Enter", delay=SEARCH_ENTER_HOLD_MS)
    except Exception as error:
        raise RuntimeError(
            "TikTok tracking/order search could not send Enter to the focused "
            "search field. The barcode was entered but the search was not confirmed."
        ) from error

    print(f"TIKTOK SEARCH: Enter sent for {search_by} {query}.")
    # Allow TikTok to dispatch the query before inspecting asynchronous rows.
    page.wait_for_timeout(500)
    row = _find_result_row(
        page,
        query,
        search_by,
        previous_return_ids=previous_return_ids,
        query_changed=(previous_query != query),
    )
    row.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    data = _extract_row_data(row)
    order_id = _text(data.get("order_id"))
    return_order_id = _text(data.get("return_order_id"))
    if not order_id:
        raise ValueError("TikTok search result has no Order ID.")
    if not return_order_id:
        raise ValueError("TikTok search result has no Return Order ID.")

    if search_by == "Order ID" and order_id != query:
        raise ValueError(
            f"Wrong TikTok order found. Expected {query}, got {order_id}."
        )
    if search_by == "Return Order ID" and return_order_id != query:
        raise ValueError(
            "Wrong TikTok return order found. "
            f"Expected {query}, got {return_order_id}."
        )

    popover = _open_product_details(page, row)
    products = _extract_products_from_popover(popover)
    if not products:
        raise ValueError(
            "TikTok return was found, but Seller SKU / QTY could not be read "
            "from the product details popover."
        )

    count_match = re.search(r"(\d+)", _text(data.get("item_count_text")))
    if count_match and int(count_match.group(1)) != len(products):
        raise ValueError(
            "TikTok product popover count did not match the return row. "
            f"Row shows {count_match.group(1)} item(s), popover exposed "
            f"{len(products)}. Retry the scan before submitting."
        )

    data["items"] = products
    data["platform"] = "TikTok"
    data["tracking_number"] = query if search_by == "Tracking Number" else ""
    data["search_query"] = query
    data["search_by"] = search_by
    data["return_url"] = page.url
    data["value_source"] = "TikTok return Refund total"
    return data


def get_tiktok_return_by_tracking(page, tracking_number: str) -> dict:
    return get_tiktok_return_order(
        page,
        tracking_number,
        search_by="Tracking Number",
    )


__all__ = [
    "get_tiktok_return_order",
    "get_tiktok_return_by_tracking",
]
