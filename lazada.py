import re

DEFAULT_TIMEOUT = 30_000
SEARCH_READY_TIMEOUT = 12_000
SEARCH_RESULT_TIMEOUT = 30_000

SEARCH_INPUT_SELECTOR = '#filters[name="filters"]'
SEARCH_BUTTON_SELECTOR = '.next-search-icon[aria-label="Search"]'
ORDER_CARD_SELECTOR = 'div.next-card.list-item'
LOGIN_BUTTON_SELECTOR = 'button.login-button'
LOGIN_ACCOUNT_SELECTOR = '#account'
LOGIN_PASSWORD_SELECTOR = '#password'
VALID_SEARCH_FILTERS = {"Order ID", "Tracking Number"}

_MONEY_CLEAN_RE = re.compile(r"[^\d.-]")


def _text(value) -> str:
    return str(value or "").strip()


def _normalized_token(value) -> str:
    return re.sub(r"\s+", "", _text(value)).upper()


def _parse_money(text: str) -> float:
    cleaned = _MONEY_CLEAN_RE.sub("", _text(text).replace(",", ""))
    if not cleaned:
        return 0.0
    return float(cleaned)


def _search_group(page):
    search = page.locator(SEARCH_INPUT_SELECTOR)
    search.wait_for(state="visible", timeout=SEARCH_READY_TIMEOUT)
    return search.locator(
        "xpath=ancestor::span[contains(concat(' ', normalize-space(@class), ' '), "
        "' next-search ')][1]"
    )


def _current_search_filter(group) -> str:
    current = group.locator(".next-search-left-addon em[title]").first
    try:
        if current.count():
            title = _text(current.get_attribute("title"))
            return title or _text(current.inner_text(timeout=1_000))
    except Exception:
        pass

    combo = group.locator(
        '.next-search-left-addon input[role="combobox"][readonly]'
    ).first
    try:
        return _text(combo.get_attribute("aria-valuetext"))
    except Exception:
        return ""


def _ensure_search_filter(page, filter_name: str):
    """Select Lazada's Order ID / Tracking Number search filter reliably."""
    filter_name = _text(filter_name)
    if filter_name not in VALID_SEARCH_FILTERS:
        raise ValueError(f"Unsupported Lazada search filter: {filter_name}")

    group = _search_group(page)
    if _current_search_filter(group) == filter_name:
        return

    trigger = group.locator(".next-search-left-addon .next-select-trigger").first
    if not trigger.count():
        trigger = group.locator(".next-search-left-addon .next-select").first

    trigger.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    trigger.click()

    option = page.locator(
        f'ul.next-select-menu:visible li[role="option"][title="{filter_name}"]'
    ).last
    if not option.count():
        option = page.get_by_role("option", name=filter_name, exact=True).last

    option.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    option.click()

    # Fusion/Next updates the select asynchronously. Verify before typing so a
    # barcode never gets searched under the previous filter.
    for _ in range(20):
        if _current_search_filter(group) == filter_name:
            return
        page.wait_for_timeout(100)

    raise RuntimeError(
        f"Lazada search filter did not change to {filter_name}."
    )


def _try_auto_login(page) -> bool:
    """
    Click Lazada's Login button only when Chrome has already populated both
    account and password fields. Credentials are never stored in this code.
    """
    button = page.locator(LOGIN_BUTTON_SELECTOR).first
    try:
        button.wait_for(state="visible", timeout=2_000)
    except Exception:
        return False

    account = page.locator(LOGIN_ACCOUNT_SELECTOR).first
    password = page.locator(LOGIN_PASSWORD_SELECTOR).first

    for _ in range(20):
        try:
            account_value = _text(account.input_value(timeout=500))
            password_value = _text(password.input_value(timeout=500))
        except Exception:
            account_value = ""
            password_value = ""

        if account_value and password_value:
            button.click()
            try:
                page.locator(SEARCH_INPUT_SELECTOR).wait_for(
                    state="visible",
                    timeout=20_000,
                )
                return True
            except Exception:
                return False

        page.wait_for_timeout(100)

    return False


def _wait_until_ready(page):
    """
    Ensure Lazada Return Orders is ready. When Chrome has remembered the
    account/password, automatically click Login as requested; otherwise leave
    the login page open for manual completion.
    """
    try:
        page.locator(SEARCH_INPUT_SELECTOR).wait_for(
            state="visible",
            timeout=3_000,
        )
        return
    except Exception:
        pass

    if _try_auto_login(page):
        return

    try:
        page.locator(SEARCH_INPUT_SELECTOR).wait_for(
            state="visible",
            timeout=SEARCH_READY_TIMEOUT,
        )
    except Exception as error:
        raise RuntimeError(
            "Lazada Return Orders is not ready. If Seller Center opened a login "
            "or verification page, complete it in the processor Chrome window, "
            "then scan/search again. If Chrome already filled the saved Lazada "
            "credentials, the processor will click Login automatically."
        ) from error


def _extract_card_data(card) -> dict:
    """Extract one Lazada order card and all rendered return-item rows."""
    return card.evaluate(
        r"""
        card => {
            const clean = value => (value || "").replace(/\s+/g, " ").trim();

            const labelValue = (root, label) => {
                const wanted = label.replace(/:$/, "").trim();
                const labels = [...root.querySelectorAll(
                    ".order-card-description-label"
                )];
                for (const node of labels) {
                    const found = clean(node.textContent).replace(/:$/, "");
                    if (found !== wanted) continue;
                    const box = node.parentElement;
                    const value = box?.querySelector(
                        ".order-card-description-value"
                    );
                    return clean(value?.textContent);
                }
                return "";
            };

            const numberFromMoney = text => {
                const value = Number(
                    clean(text).replace(/,/g, "").replace(/[^0-9.-]/g, "")
                );
                return Number.isFinite(value) ? value : 0;
            };

            const productTitle = item => {
                const title = item.querySelector("h6.next-typography-title");
                if (!title) return "";
                const clone = title.cloneNode(true);
                clone.querySelectorAll(".tagWrap").forEach(node => node.remove());
                return clean(clone.textContent);
            };

            const orderId = labelValue(card, "Order ID");
            const returnOrderId = labelValue(card, "Return Order ID");
            const orderDate = labelValue(card, "Order Date");
            const returnOrderDate = labelValue(card, "Return Order Date");
            const customer = clean(
                card.querySelector("button.chat-button .next-btn-helper")
                    ?.textContent
            );

            const items = [...card.querySelectorAll("li.next-list-item")]
                .map(item => {
                    const sku = labelValue(item, "Seller SKU ID");
                    if (!sku) return null;

                    const refundText = labelValue(item, "Refund Amount");
                    const paymentText = labelValue(item, "My Payment");
                    const tag = clean(
                        item.querySelector(".tagWrap .next-tag-body")?.textContent
                    );
                    const actions = [...item.querySelectorAll("button")]
                        .map(button => clean(button.textContent))
                        .filter(Boolean);

                    return {
                        sku,
                        quantity: 1,
                        quantity_assumed: true,
                        product_name: productTitle(item),
                        return_type: tag,
                        return_item_id: labelValue(item, "Return Item ID"),
                        order_item_id: labelValue(item, "Order Item ID"),
                        source_status: labelValue(item, "Status"),
                        refund_text: refundText,
                        refund_amount: numberFromMoney(refundText),
                        my_payment_text: paymentText,
                        my_payment: numberFromMoney(paymentText),
                        return_reason: labelValue(item, "Return Reason"),
                        tracking_number: labelValue(item, "Tracking Number"),
                        logistic_status: labelValue(item, "Logistic Status"),
                        sla: labelValue(item, "SLA"),
                        actions,
                    };
                })
                .filter(Boolean);

            return {
                order_id: orderId,
                return_order_id: returnOrderId,
                order_date: orderDate,
                return_order_date: returnOrderDate,
                customer,
                items,
            };
        }
        """
    )


def _find_result_card(page, query: str, search_by: str):
    if search_by == "Order ID":
        anchor = page.locator(
            f'a[href*="tradeOrderId={query}"]'
        ).first
        anchor.wait_for(state="visible", timeout=SEARCH_RESULT_TIMEOUT)
        card = anchor.locator(
            "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), "
            "' next-card ') and contains(concat(' ', normalize-space(@class), ' '), "
            "' list-item ')][1]"
        )
    else:
        card = page.locator(ORDER_CARD_SELECTOR).filter(has_text=query).first
        card.wait_for(state="visible", timeout=SEARCH_RESULT_TIMEOUT)

    card.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    return card


def get_lazada_return_order(
    page,
    query: str,
    *,
    search_by: str = "Order ID",
) -> dict:
    """
    Search Lazada Return Orders by Order ID or Tracking Number.

    For Tracking Number searches, only items whose Tracking Number matches the
    scanned waybill are returned. This prevents a multi-parcel Lazada order from
    accidentally loading unrelated return items from the same Order ID.
    """
    query = _text(query)
    search_by = _text(search_by) or "Order ID"

    if not query:
        raise ValueError(f"Lazada {search_by} is empty.")
    if search_by not in VALID_SEARCH_FILTERS:
        raise ValueError(f"Unsupported Lazada search mode: {search_by}")

    _wait_until_ready(page)
    _ensure_search_filter(page, search_by)

    search = page.locator(SEARCH_INPUT_SELECTOR)
    search.fill(query)
    group = _search_group(page)
    group.locator(SEARCH_BUTTON_SELECTOR).first.click()

    try:
        card = _find_result_card(page, query, search_by)
    except Exception as error:
        raise ValueError(
            f"Lazada return was not found for {search_by}: {query}. "
            "Check the value and the current Lazada return-status tab."
        ) from error

    data = _extract_card_data(card)
    found_order_id = _text(data.get("order_id"))
    if not found_order_id:
        raise ValueError("The Lazada search result has no Order ID.")

    if search_by == "Order ID" and found_order_id != query:
        raise ValueError(
            "Wrong Lazada return card found. "
            f"Expected {query}, got {found_order_id or 'blank'}"
        )

    all_items = data.get("items") or []
    if search_by == "Tracking Number":
        wanted = _normalized_token(query)
        items = [
            item for item in all_items
            if _normalized_token(item.get("tracking_number")) == wanted
        ]
        if not items:
            seen = sorted({
                _text(item.get("tracking_number"))
                for item in all_items
                if _text(item.get("tracking_number"))
            })
            raise ValueError(
                "Lazada opened a result card but the scanned Tracking Number "
                f"was not present in its item rows. Found: {', '.join(seen) or 'none'}"
            )
        data["items"] = items
        data["tracking_number"] = query
    else:
        items = all_items
        data["tracking_number"] = ""

    if not items:
        raise ValueError(
            f"No Lazada return items were found for {search_by} {query}."
        )

    total_refund = round(
        sum(float(item.get("refund_amount") or 0) for item in items),
        2,
    )

    data["refund_value"] = total_refund
    data["refund_text"] = f"₱{total_refund:,.2f}"
    data["platform"] = "Lazada"
    data["value_mode"] = "item_amounts"
    data["value_source"] = "Lazada item Refund Amount"
    data["return_url"] = page.url
    data["search_query"] = query
    data["search_by"] = search_by
    return data


def get_lazada_return_by_tracking(page, tracking_number: str) -> dict:
    """Convenience wrapper for barcode/waybill scanning."""
    return get_lazada_return_order(
        page,
        tracking_number,
        search_by="Tracking Number",
    )


def suggested_processor_status(item: dict) -> str:
    """Auto-mark Returned only when Lazada clearly says it reached the seller."""
    source_status = _text(item.get("source_status")).lower()
    logistic_status = _text(item.get("logistic_status")).lower()

    if source_status == "return delivered" or "delivered to seller" in logistic_status:
        return "Returned"
    return ""


__all__ = [
    "get_lazada_return_order",
    "get_lazada_return_by_tracking",
    "suggested_processor_status",
]
