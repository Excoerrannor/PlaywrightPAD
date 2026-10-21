import re
from urllib.parse import quote, urlencode

LARK_FORM_BASE_URL = (
    "https://kjx72am2njb.sg.larksuite.com/share/base/form/"
    "shrlgCvlgAlYpqw3TAThRikY3ig"
)

DEFAULT_TIMEOUT = 30_000
SLOW_TIMEOUT = 60_000
RETURNED_STATUS = "Returned"


def _text(value) -> str:
    return str(value or "").strip()


def _progress(callback, message: str):
    if callback:
        callback(message)
    print(message)


def _normalize_grade(grade: str) -> str:
    grade = _text(grade)
    if not grade:
        return ""
    return grade if grade.lower().startswith("grade ") else f"Grade {grade}"


def build_prefilled_lark_url(
    *,
    order_id: str,
    sku: str,
    quantity: int,
    value: float,
    classification: str,
    status: str,
    decision: str,
    platform: str,
    transfer_id: str,
    transfer_link: str,
    remarks: str = "",
    grade: str = "",
) -> str:
    """Build the Lark Item Returns prefill URL."""
    params = {
        "prefill_Order ID": order_id,
        "prefill_SKU": sku,
        "prefill_QTY": str(quantity),
        "prefill_Value": str(value),
        "prefill_Classification": classification,
        "prefill_Status": status,
        "prefill_Decision": decision,
        "prefill_Platform": platform,
    }

    # Not Returned items intentionally omit both fields so Lark leaves them blank.
    if transfer_id:
        params["prefill_Transfer ID"] = transfer_id
    if transfer_link:
        params["prefill_Transfer Link"] = transfer_link
    if remarks:
        params["prefill_Remarks"] = remarks

    if classification == "Unsealed":
        normalized = _normalize_grade(grade)
        if not normalized:
            raise ValueError("Grade is required for an Unsealed Lark return.")
        params["prefill_Grade"] = normalized

    return (
        f"{LARK_FORM_BASE_URL}?"
        + urlencode(params, quote_via=quote, safe="")
    )


def get_or_open_lark_page(context):
    """Create a fresh tab, as Lark prefills are unreliable on reused form tabs.

    The tab stays inside the existing persistent Chrome profile, so Lark
    sign-in remains available. A failed form is left open for inspection.
    """
    return context.new_page()


FIELD_IDS = {
    "order_id": "fldGfpOgy3",
    "sku": "fldZmVCLSz",
    "quantity": "fldp1RHjbO",
    "value": "fld7ICAkSy",
    "classification": "fldc6INoIL",
    "status": "flduWjJhXm",
    "decision": "fldsuY8UMD",
    "platform": "flde3CocnE",
    "transfer_id": "fldLxm5LZH",
    "transfer_link": "fldKACH12T",
    "remarks": "fldxl8I6rt",
    "grade": "fld6aPiebx",
}


def _field_card(page, field_id: str):
    return page.locator(f"#field-item-{field_id}")


def _clean_editor_text(value: str) -> str:
    return _text(value).replace("\u200b", "").strip()


def _wait_for_form_ready(page):
    try:
        _field_card(page, FIELD_IDS["order_id"]).wait_for(
            state="visible",
            timeout=SLOW_TIMEOUT,
        )
    except Exception as error:
        live_url = page.url
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=2_000)
        except Exception:
            pass
        if "login" in live_url.lower() or "sign in" in body_text.lower():
            raise RuntimeError(
                "Lark is asking for login. Sign in to Lark in the processor "
                "Chrome window, then press Submit again."
            ) from error
        raise RuntimeError(
            "The Lark Item Returns form did not become ready."
        ) from error


def _text_editor(page, field_id: str):
    editor = _field_card(page, field_id).locator(
        '[contenteditable="true"]'
    ).first
    editor.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    return editor


def _fill_text_field(page, field_id: str, value: str):
    editor = _text_editor(page, field_id)
    wanted = _text(value)
    if _clean_editor_text(editor.inner_text()) != wanted:
        editor.fill(wanted)


def _fill_number_field(page, field_id: str, value):
    input_box = _field_card(page, field_id).locator("input").first
    input_box.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    current = _clean_editor_text(input_box.input_value()).replace(",", "")
    try:
        already_correct = float(current) == float(value)
    except (TypeError, ValueError):
        already_correct = False
    if not already_correct:
        input_box.fill(str(value))


def _selected_option_values(card) -> list[str]:
    """Read existing selections without clicking or toggling any option."""
    return [
        _clean_editor_text(value)
        for value in card.locator(
            ".base-component-select-list-editor-option-checked "
            ".base-component-select-list-editor-text"
        ).all_text_contents()
        if _clean_editor_text(value)
    ]


def _select_option(page, field_id: str, option_text: str):
    """Idempotent single-select: never click an already selected option.

    Some Lark radio-style selectors toggle OFF when clicked a second time.
    Exact matching also prevents 'Returned' matching 'Not Returned'.
    """
    option_text = _text(option_text)
    if not option_text:
        raise ValueError(f"A required Lark option for {field_id} is blank.")

    card = _field_card(page, field_id)
    card.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    if _selected_option_values(card) == [option_text]:
        return

    exact_label = re.compile(rf"^\s*{re.escape(option_text)}\s*$")
    option = card.locator(
        ".base-component-select-list-editor-option"
    ).filter(has_text=exact_label).first
    option.wait_for(state="visible", timeout=SLOW_TIMEOUT)

    # The async prefill can finish while locating the option. Check again.
    if _selected_option_values(card) == [option_text]:
        return
    option.click()

    selected = card.locator(
        ".base-component-select-list-editor-option-checked "
        ".base-component-select-list-editor-text"
    ).filter(has_text=exact_label).first
    try:
        selected.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    except Exception as error:
        actual = _selected_option_values(card)
        raise RuntimeError(
            f"Lark could not select {option_text!r} for {field_id}. "
            f"Selected value(s): {actual!r}."
        ) from error
    if _selected_option_values(card) != [option_text]:
        raise RuntimeError(
            f"Lark {field_id} selection was not stable: "
            f"{_selected_option_values(card)!r}."
        )


def _read_text_field(page, field_id: str) -> str:
    return _clean_editor_text(_text_editor(page, field_id).inner_text())


def _read_number_field(page, field_id: str) -> str:
    input_box = _field_card(page, field_id).locator("input").first
    input_box.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return _clean_editor_text(input_box.input_value())


def _read_selected_option(page, field_id: str) -> str:
    selected = _field_card(page, field_id).locator(
        ".base-component-select-list-editor-option-checked "
        ".base-component-select-list-editor-text"
    ).first
    selected.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return _clean_editor_text(selected.inner_text())


def _verify_form_values(page, expected: dict):
    text_checks = {
        "Order ID": (FIELD_IDS["order_id"], expected["order_id"]),
        "SKU": (FIELD_IDS["sku"], expected["sku"]),
        "Transfer ID": (FIELD_IDS["transfer_id"], expected["transfer_id"]),
        "Transfer Link": (FIELD_IDS["transfer_link"], expected["transfer_link"]),
        "Remarks": (FIELD_IDS["remarks"], expected["remarks"]),
    }
    for label, (field_id, wanted) in text_checks.items():
        actual = _read_text_field(page, field_id)
        if actual != _text(wanted):
            raise RuntimeError(
                f"Lark {label} verification failed. "
                f"Expected {_text(wanted)!r}, got {actual!r}."
            )

    qty_actual = _read_number_field(page, FIELD_IDS["quantity"])
    try:
        qty_ok = int(float(qty_actual.replace(",", ""))) == int(expected["quantity"])
    except (TypeError, ValueError):
        qty_ok = False
    if not qty_ok:
        raise RuntimeError(
            "Lark QTY verification failed. "
            f"Expected {int(expected['quantity'])}, got {qty_actual!r}."
        )

    value_actual = _read_number_field(page, FIELD_IDS["value"])
    try:
        actual_value = float(value_actual.replace(",", ""))
        expected_value = float(expected["value"])
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Lark Value verification failed: {value_actual!r}."
        ) from error
    if abs(actual_value - expected_value) > 0.005:
        raise RuntimeError(
            "Lark Value verification failed. "
            f"Expected {expected_value:.2f}, got {actual_value:.2f}."
        )

    select_checks = {
        "Classification": (FIELD_IDS["classification"], expected["classification"]),
        "Status": (FIELD_IDS["status"], expected["status"]),
        "Decision": (FIELD_IDS["decision"], expected["decision"]),
        "Platform": (FIELD_IDS["platform"], expected["platform"]),
    }
    for label, (field_id, wanted) in select_checks.items():
        actual = _read_selected_option(page, field_id)
        if actual != _text(wanted):
            raise RuntimeError(
                f"Lark {label} verification failed. "
                f"Expected {_text(wanted)!r}, got {actual!r}."
            )

    if expected["classification"] == "Unsealed":
        wanted_grade = _normalize_grade(expected["grade"])
        actual_grade = _read_selected_option(page, FIELD_IDS["grade"])
        if actual_grade != wanted_grade:
            raise RuntimeError(
                "Lark Grade verification failed. "
                f"Expected {wanted_grade!r}, got {actual_grade!r}."
            )


def _fill_lark_form(page, expected: dict):
    """Wait for URL prefill, fill any missing values, and verify everything."""
    _wait_for_form_ready(page)

    # Lark applies prefill asynchronously. A new tab often fills correctly
    # after hydration; acting before that point can toggle values back off.
    # If prefill did not arrive, continue to explicit field filling below.
    try:
        page.wait_for_function(
            """expected => {
                const editor = document.querySelector(
                    '#field-item-fldGfpOgy3 [contenteditable="true"]'
                );
                const order_id = (editor?.textContent || '')
                    .replace(/\u200b/g, '').trim();
                const fieldIds = {
                    classification: 'fldc6INoIL',
                    status: 'flduWjJhXm',
                    decision: 'fldsuY8UMD',
                    platform: 'flde3CocnE',
                };
                return order_id === expected.order_id &&
                    Object.entries(fieldIds).every(([name, id]) => {
                        const selected = document.querySelector(
                            '#field-item-' + id + ' ' +
                            '.base-component-select-list-editor-option-checked ' +
                            '.base-component-select-list-editor-text'
                        );
                        return (selected?.textContent || '').trim() === expected[name];
                    });
            }""",
            arg={name: _text(expected[name]) for name in (
                "order_id", "classification", "status", "decision", "platform"
            )},
            timeout=6_000,
        )
    except Exception:
        # An incomplete prefill is not fatal: set only the missing fields.
        print("LARK PREFILL: Incomplete after waiting; correcting form fields.")

    # Select choices first because Classification can change conditional
    # visibility (Grade) and may rerender part of the form.
    _select_option(page, FIELD_IDS["classification"], expected["classification"])
    _select_option(page, FIELD_IDS["status"], expected["status"])
    _select_option(page, FIELD_IDS["decision"], expected["decision"])
    _select_option(page, FIELD_IDS["platform"], expected["platform"])

    if expected["classification"] == "Unsealed":
        _field_card(page, FIELD_IDS["grade"]).wait_for(
            state="visible", timeout=SLOW_TIMEOUT
        )
        _select_option(
            page, FIELD_IDS["grade"], _normalize_grade(expected["grade"])
        )

    # Fill text/number values after select-driven rerenders are complete.
    _fill_text_field(page, FIELD_IDS["order_id"], expected["order_id"])
    _fill_text_field(page, FIELD_IDS["sku"], expected["sku"])
    _fill_number_field(page, FIELD_IDS["quantity"], int(expected["quantity"]))
    _fill_number_field(page, FIELD_IDS["value"], float(expected["value"]))
    _fill_text_field(page, FIELD_IDS["transfer_id"], expected["transfer_id"])
    _fill_text_field(page, FIELD_IDS["transfer_link"], expected["transfer_link"])
    _fill_text_field(page, FIELD_IDS["remarks"], expected["remarks"])

    _verify_form_values(page, expected)


def _visible_form_errors(page) -> str:
    messages = []
    for selector in ('[class*="error"]', '[class*="invalid"]', '[role="alert"]'):
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 20)):
                node = locator.nth(index)
                if not node.is_visible():
                    continue
                value = _clean_editor_text(node.inner_text(timeout=500))
                if value and value not in messages:
                    messages.append(value)
        except Exception:
            continue
    return " | ".join(messages[:8])


def file_lark_return(
    page,
    *,
    order_id: str,
    sku: str,
    quantity: int,
    value: float,
    classification: str,
    status: str,
    decision: str,
    platform: str,
    transfer_id: str,
    transfer_link: str,
    remarks: str = "",
    grade: str = "",
    progress_callback=None,
) -> dict:
    """Open, verify, and submit one prefilled Lark return form."""
    prefilled_url = build_prefilled_lark_url(
        order_id=order_id,
        sku=sku,
        quantity=quantity,
        value=value,
        classification=classification,
        status=status,
        decision=decision,
        platform=platform,
        transfer_id=transfer_id,
        transfer_link=transfer_link,
        remarks=remarks,
        grade=grade,
    )

    _progress(progress_callback, f"Opening prefilled Lark form for {sku}...")
    page.goto(
        prefilled_url,
        wait_until="domcontentloaded",
        timeout=SLOW_TIMEOUT,
    )

    expected = {
        "order_id": order_id,
        "sku": sku,
        "quantity": quantity,
        "value": value,
        "classification": classification,
        "status": status,
        "decision": decision,
        "platform": platform,
        "transfer_id": transfer_id,
        "transfer_link": transfer_link,
        "remarks": remarks,
        "grade": grade,
    }
    _progress(progress_callback, f"Filling and verifying Lark form for {sku}...")
    _fill_lark_form(page, expected)

    button = page.get_by_role("button", name="File Return", exact=True)
    button.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    button.scroll_into_view_if_needed()

    _progress(progress_callback, f"Submitting Lark return for {sku}...")
    button.click()

    submitted = page.get_by_text("Submitted", exact=True).first
    try:
        submitted.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    except Exception as error:
        details = _visible_form_errors(page)
        suffix = f" Visible form message(s): {details}" if details else ""
        raise RuntimeError(
            "Lark did not confirm the submission with the 'Submitted' page."
            + suffix
        ) from error

    _progress(
        progress_callback,
        f"Lark return submitted successfully for {sku}.",
    )

    return {
        "order_id": order_id,
        "sku": sku,
        "quantity": quantity,
        "value": value,
        "classification": classification,
        "status": status,
        "decision": decision,
        "platform": platform,
        "transfer_id": transfer_id,
        "transfer_link": transfer_link,
        "remarks": remarks,
        "grade": (
            _normalize_grade(grade)
            if classification == "Unsealed"
            else ""
        ),
        "prefilled_url": prefilled_url,
        "submitted": True,
    }


def _refund_value(return_case: dict | None) -> float:
    if not return_case:
        raise ValueError("Return/refund data is required for Lark filing.")
    try:
        value = float(return_case["refund_value"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Return/refund value is missing or invalid.") from error
    if value < 0:
        raise ValueError("Return/refund value cannot be negative.")
    return value


def _value_source(return_case: dict | None) -> str:
    if not return_case:
        return "Return/refund value"
    return _text(return_case.get("value_source")) or "Return/refund value"


def _record_value(return_case: dict | None, items: list[dict]) -> float:
    """
    Shopee keeps the existing order/refund-total behavior.
    Lazada can opt into item-level values by setting value_mode=item_amounts.
    """
    default_value = _refund_value(return_case)
    if _text((return_case or {}).get("value_mode")) != "item_amounts":
        return default_value

    total = 0.0
    for item in items:
        sku = _text(item.get("sku"))
        try:
            amount = float(item.get("amount", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid return amount for {sku or 'item'}.") from error
        if amount < 0:
            raise ValueError(f"Return amount for {sku or 'item'} cannot be negative.")
        total += amount
    return round(total, 2)

def _build_returned_item_pool(items: list[dict]) -> list[dict]:
    pool = []
    for item in items:
        sku = _text(item.get("sku"))
        if not sku:
            raise ValueError("A returned product has a blank SKU.")
        try:
            quantity = int(item.get("quantity", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid QTY for {sku}.") from error
        if quantity <= 0:
            raise ValueError(f"QTY for {sku} must be at least 1.")
        pool.append({"item": item, "remaining": quantity})
    return pool


def _matches_transfer(item: dict, transfer: dict, sku: str) -> bool:
    checks = (
        ("sku", sku),
        ("decision", _text(transfer.get("decision"))),
        ("classification", _text(transfer.get("classification"))),
        ("status", _text(transfer.get("status"))),
    )
    return all(
        not expected or _text(item.get(field)) == expected
        for field, expected in checks
    )


def _take_items_for_transfer(
    transfer: dict,
    pool: list[dict],
) -> list[dict]:
    """Quantity-aware matching that safely supports duplicate SKU rows."""
    matched = []

    for transfer_item in transfer.get("items", []):
        sku = _text(transfer_item.get("sku"))
        try:
            needed = int(transfer_item.get("quantity", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid Odoo transfer QTY for {sku}.") from error

        if not sku or needed <= 0:
            raise ValueError("Odoo transfer contains an invalid SKU/QTY row.")

        for entry in pool:
            if needed <= 0:
                break
            if entry["remaining"] <= 0:
                continue

            item = entry["item"]
            if not _matches_transfer(item, transfer, sku):
                continue

            allocated = min(entry["remaining"], needed)
            allocated_item = dict(item)
            allocated_item["quantity"] = allocated
            matched.append(allocated_item)

            entry["remaining"] -= allocated
            needed -= allocated

        if needed:
            raise ValueError(
                f"Could not match {needed} remaining unit(s) of {sku} "
                f"to Odoo Transfer {_text(transfer.get('transfer_id'))}. "
                f"Expected handling: {_text(transfer.get('classification'))} / "
                f"{_text(transfer.get('decision'))} / "
                f"{_text(transfer.get('status'))}."
            )

    if not matched:
        raise ValueError(
            f"Odoo Transfer {_text(transfer.get('transfer_id'))} "
            "contains no returned items."
        )
    return matched


def _shared_value(
    items: list[dict],
    field: str,
    label: str,
    *,
    default: str = "",
) -> str:
    values = list(dict.fromkeys(
        _text(item.get(field, default))
        for item in items
    ))
    if len(values) > 1:
        raise ValueError(
            f"Odoo Transfer contains different {label} values: "
            + ", ".join(values)
        )
    return values[0] if values else default


def _combine_transfer_remarks(items: list[dict]) -> str:
    parts = []
    for item in items:
        details = []
        grade = _text(item.get("grade"))
        remarks = _text(item.get("remarks"))
        if grade:
            details.append(_normalize_grade(grade))
        if remarks:
            details.append(remarks)
        if details:
            parts.append(f"{_text(item.get('sku'))}: " + " | ".join(details))
    return " ; ".join(parts)


def _transfer_record(
    transfer: dict,
    pool: list[dict],
    return_case: dict | None,
    index: int,
) -> dict:
    transfer_id = _text(transfer.get("transfer_id"))
    transfer_url = _text(transfer.get("transfer_url"))
    if not transfer_id or not transfer_url:
        raise ValueError(
            f"Odoo Transfer #{index} is missing its Transfer ID or Transfer Link."
        )

    items = _take_items_for_transfer(transfer, pool)
    decision = _text(transfer.get("decision")) or _shared_value(
        items, "decision", "Decision"
    )
    classification = _text(transfer.get("classification")) or _shared_value(
        items, "classification", "Classification"
    )
    status = _text(transfer.get("status")) or _shared_value(
        items, "status", "Status"
    )
    platform = _shared_value(
        items, "platform", "Platform", default="Shopee"
    ) or "Shopee"

    grade = ""
    if classification == "Unsealed":
        grade = _shared_value(items, "grade", "Grade")
        if not grade:
            raise ValueError(
                f"Grade is required for Unsealed Transfer {transfer_id}."
            )

    return {
        "order_id": None,  # injected by caller
        "sku": ", ".join(
            f"{_text(item.get('sku'))}_{int(item['quantity'])}"
            for item in items
        ),
        "quantity": sum(int(item["quantity"]) for item in items),
        "value": _record_value(return_case, items),
        "classification": classification,
        "status": status,
        "decision": decision,
        "platform": platform,
        "transfer_id": transfer_id,
        "transfer_link": transfer_url,
        "remarks": _combine_transfer_remarks(items),
        "grade": grade,
        "_meta": {
            "filing_type": "odoo_transfer",
            "transfer_index": index,
            "value_source": _value_source(return_case),
            "items": [
                {
                    "sku": _text(item.get("sku")),
                    "quantity": int(item["quantity"]),
                }
                for item in items
            ],
        },
    }


def _direct_record(item: dict, return_case: dict | None) -> dict:
    sku = _text(item.get("sku"))
    quantity = int(item.get("quantity", 0))
    return {
        "order_id": None,  # injected by caller
        "sku": sku,
        "quantity": quantity,
        "value": _record_value(return_case, [item]),
        "classification": _text(item.get("classification")),
        "status": _text(item.get("status")),
        "decision": _text(item.get("decision")),
        "platform": _text(item.get("platform")) or "Shopee",
        "transfer_id": "",
        "transfer_link": "",
        "remarks": _text(item.get("remarks")),
        "grade": _text(item.get("grade")),
        "_meta": {
            "filing_type": "not_returned_direct",
            "value_source": _value_source(return_case),
            "items": [{"sku": sku, "quantity": quantity}],
        },
    }


def _submit_record(
    page,
    record: dict,
    order_id: str,
    progress_callback,
) -> dict:
    record = dict(record)
    meta = record.pop("_meta")
    record["order_id"] = order_id

    result = file_lark_return(
        page=page,
        progress_callback=progress_callback,
        **record,
    )
    result.update(meta)
    result["item_count"] = len(meta["items"])
    result["value_source"] = meta.get("value_source", "Return/refund value")
    return result


def file_lark_returns(
    context,
    *,
    order_id: str,
    returned_products: list[dict],
    return_case: dict | None,
    case_decision: dict | None,
    odoo_results: dict | None,
    progress_callback=None,
) -> list[dict]:
    """
    Returned items -> one Lark filing per Odoo Transfer ID.
    Not Returned items -> direct Lark filing with blank Transfer ID/Link.
    """
    if not order_id:
        raise ValueError("Order ID is required for Lark filing.")
    if not returned_products:
        raise ValueError("No returned products are available for Lark filing.")

    _refund_value(return_case)  # validate source value before any filing
    physically_returned = [
        item for item in returned_products
        if _text(item.get("status")) == RETURNED_STATUS
    ]
    not_returned = [
        item for item in returned_products
        if _text(item.get("status")) != RETURNED_STATUS
    ]

    if physically_returned and not odoo_results:
        raise ValueError(
            "Odoo processing is required for item(s) with Status = Returned."
        )

    transfers = odoo_results.get("returns", []) if odoo_results else []
    pool = _build_returned_item_pool(physically_returned)

    results = []
    previous_success_page = None

    def file_in_fresh_tab(record: dict) -> dict:
        nonlocal previous_success_page
        page = get_or_open_lark_page(context)
        page.bring_to_front()
        # On failure, leave this tab open for the operator to inspect.
        result = _submit_record(page, record, order_id, progress_callback)
        # Keep only the latest successful 'Submitted' tab open.
        if previous_success_page is not None:
            try:
                if not previous_success_page.is_closed():
                    previous_success_page.close()
            except Exception:
                pass
        previous_success_page = page
        return result

    for index, transfer in enumerate(transfers, start=1):
        record = _transfer_record(transfer, pool, return_case, index)
        _progress(
            progress_callback,
            f"Filing Lark Transfer {index}/{len(transfers)}: "
            f"{record['transfer_id']} | {record['sku']}",
        )
        results.append(file_in_fresh_tab(record))

    for index, item in enumerate(not_returned, start=1):
        record = _direct_record(item, return_case)
        _progress(
            progress_callback,
            f"Filing direct Lark item {index}/{len(not_returned)}: "
            f"{record['sku']} | {record['status']}",
        )
        results.append(file_in_fresh_tab(record))

    if not results:
        raise ValueError("No Lark filing records were generated.")
    return results


__all__ = [
    "build_prefilled_lark_url",
    "get_or_open_lark_page",
    "file_lark_return",
    "file_lark_returns",
]
