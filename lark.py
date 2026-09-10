from urllib.parse import urlencode, quote

LARK_FORM_BASE_URL = (
    "https://kjx72am2njb.sg.larksuite.com/share/base/form/"
    "shrlgCvlgAlYpqw3TAThRikY3ig"
)

DEFAULT_TIMEOUT = 30_000
SLOW_TIMEOUT = 60_000


def _normalize_grade(grade: str) -> str:
    grade = (grade or "").strip()

    if not grade:
        return ""

    if grade.lower().startswith("grade "):
        return grade

    return f"Grade {grade}"


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
    """
    Build a Lark Base prefilled-form URL using the visible form field names.

    Grade is included only for Classification = Unsealed because the form
    conditionally displays the Grade question for Unsealed returns.
    """

    params = {
        "prefill_Order ID": order_id,
        "prefill_SKU": sku,
        "prefill_QTY": str(quantity),
        "prefill_Value": str(value),
        "prefill_Classification": classification,
        "prefill_Status": status,
        "prefill_Decision": decision,
        "prefill_Platform": platform,
        "prefill_Transfer ID": transfer_id,
        "prefill_Transfer Link": transfer_link,
    }

    if remarks:
        params["prefill_Remarks"] = remarks

    if classification == "Unsealed":
        normalized_grade = _normalize_grade(grade)

        if not normalized_grade:
            raise ValueError(
                "Grade is required for an Unsealed Lark return."
            )

        params["prefill_Grade"] = normalized_grade

    query = urlencode(
        params,
        quote_via=quote,
        safe="",
    )

    return f"{LARK_FORM_BASE_URL}?{query}"


def get_or_open_lark_page(context):
    """
    Reuse the Lark Item Returns form tab when possible.
    Otherwise create a new tab in the existing persistent browser context.
    """

    for page in context.pages:
        if page.is_closed():
            continue

        if "shrlgCvlgAlYpqw3TAThRikY3ig" in page.url:
            return page

    return context.new_page()


def _verify_prefilled_form(page, expected: dict):
    """
    Lightweight safety verification before submitting.

    We validate stable text/number fields that can be inspected directly.
    Single-select fields are already populated by Lark through the prefill URL.
    """

    # Order ID
    order_id_editor = page.locator(
        '#field-item-fldGfpOgy3 [contenteditable="true"]'
    ).first

    order_id_editor.wait_for(
        state="visible",
        timeout=SLOW_TIMEOUT,
    )

    # QTY
    qty_input = page.locator(
        "#number-editor-input-fldp1RHjbO"
    )

    qty_input.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    # Value
    value_input = page.locator(
        "#number-editor-input-fld7ICAkSy"
    )

    value_input.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    # For Unsealed returns, Grade must become visible.
    if expected["classification"] == "Unsealed":
        grade_card = page.locator(
            "#field-item-fld6aPiebx"
        )

        grade_card.wait_for(
            state="visible",
            timeout=SLOW_TIMEOUT,
        )


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
    """
    Open the prefilled Lark Item Returns form and submit it.
    """

    def progress(message):
        if progress_callback:
            progress_callback(message)
        print(message)

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

    progress(
        f"Opening prefilled Lark form for {sku}..."
    )

    page.goto(
        prefilled_url,
        wait_until="domcontentloaded",
        timeout=SLOW_TIMEOUT,
    )

    _verify_prefilled_form(
        page,
        {
            "classification": classification,
        },
    )

    file_button = page.get_by_role(
        "button",
        name="File Return",
        exact=True,
    )

    file_button.wait_for(
        state="visible",
        timeout=SLOW_TIMEOUT,
    )

    progress(
        f"Submitting Lark return for {sku}..."
    )

    file_button.click()

    submitted = page.get_by_text(
        "Submitted",
        exact=True,
    ).first

    submitted.wait_for(
        state="visible",
        timeout=SLOW_TIMEOUT,
    )

    progress(
        f"Lark return submitted successfully for {sku}."
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


def _build_returned_item_pool(
    returned_products: list[dict],
) -> list[dict]:
    """
    Build a quantity-aware pool of confirmed returned-item rows.

    Duplicate SKUs are allowed because separate physical units of the same
    SKU may have different Classification / Decision / Status and therefore
    belong to different Odoo Transfer IDs.
    """

    pool = []

    for index, item in enumerate(returned_products):
        sku = str(
            item.get("sku", "")
        ).strip()

        if not sku:
            raise ValueError(
                "A returned product has a blank SKU."
            )

        try:
            quantity = int(
                item.get("quantity", 0)
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid QTY for {sku}."
            ) from error

        if quantity <= 0:
            raise ValueError(
                f"QTY for {sku} must be at least 1."
            )

        pool.append(
            {
                "index": index,
                "item": item,
                "remaining": quantity,
            }
        )

    return pool


def _pool_item_matches_transfer(
    item: dict,
    *,
    sku: str,
    decision: str,
    classification: str,
    status: str,
) -> bool:
    """
    Match one GUI/Shopee row to the Odoo transfer that it created.

    The transfer group already records Decision + Classification + Status,
    so those fields disambiguate duplicate SKU rows safely.
    """

    if str(
        item.get("sku", "")
    ).strip() != sku:
        return False

    if decision and str(
        item.get("decision", "")
    ).strip() != decision:
        return False

    if classification and str(
        item.get("classification", "")
    ).strip() != classification:
        return False

    if status and str(
        item.get("status", "")
    ).strip() != status:
        return False

    return True


def _take_items_for_transfer(
    transfer: dict,
    returned_pool: list[dict],
) -> list[dict]:
    """
    Consume the exact item quantities represented by one Odoo Transfer ID.

    This supports cases such as:

        MLE03495 | 1 | Unsealed  -> TC/IN/AAAA
        MLE03495 | 1 | Defective -> TC/IN/BBBB

    even though both rows have the same SKU.
    """

    decision = str(
        transfer.get("decision", "")
    ).strip()

    classification = str(
        transfer.get("classification", "")
    ).strip()

    status = str(
        transfer.get("status", "")
    ).strip()

    matched_items = []

    for transfer_item in transfer.get(
        "items",
        [],
    ):
        sku = str(
            transfer_item.get("sku", "")
        ).strip()

        try:
            needed = int(
                transfer_item.get("quantity", 0)
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid Odoo transfer QTY for {sku}."
            ) from error

        if not sku or needed <= 0:
            raise ValueError(
                "Odoo transfer contains an invalid SKU/QTY row."
            )

        for entry in returned_pool:
            if needed <= 0:
                break

            if entry["remaining"] <= 0:
                continue

            item = entry["item"]

            if not _pool_item_matches_transfer(
                item,
                sku=sku,
                decision=decision,
                classification=classification,
                status=status,
            ):
                continue

            allocated = min(
                entry["remaining"],
                needed,
            )

            # Use a shallow copy because the Lark representation may need
            # only part of a GUI row's quantity.
            allocated_item = dict(
                item
            )
            allocated_item["quantity"] = allocated

            matched_items.append(
                allocated_item
            )

            entry["remaining"] -= allocated
            needed -= allocated

        if needed > 0:
            raise ValueError(
                f"Could not match {needed} remaining unit(s) of {sku} "
                f"to Odoo Transfer {transfer.get('transfer_id', '')}. "
                f"Expected handling: {classification} / {decision} / {status}."
            )

    if not matched_items:
        raise ValueError(
            f"Odoo Transfer {transfer.get('transfer_id', '')} "
            "contains no returned items."
        )

    return matched_items


def _shared_item_field(
    items: list[dict],
    field: str,
    label: str,
    *,
    default: str = "",
) -> str:
    """
    Return one shared value for a single-value Lark field.

    A transfer normally has one Classification/Decision/Status because
    Odoo generated it from one return group.
    """

    values = []

    for item in items:
        value = str(
            item.get(
                field,
                default,
            )
        ).strip()

        if value not in values:
            values.append(
                value
            )

    if len(values) > 1:
        raise ValueError(
            f"Odoo Transfer contains different {label} values: "
            + ", ".join(values)
        )

    return (
        values[0]
        if values
        else default
    )


def _combine_transfer_remarks(
    items: list[dict],
) -> str:
    """
    Preserve per-SKU remarks in a single Lark filing.
    """

    parts = []

    for item in items:
        sku = str(
            item["sku"]
        ).strip()

        remarks = str(
            item.get(
                "remarks",
                "",
            )
        ).strip()

        grade = str(
            item.get(
                "grade",
                "",
            )
        ).strip()

        details = []

        if grade:
            details.append(
                f"Grade {grade}"
                if not grade.lower().startswith("grade ")
                else grade
            )

        if remarks:
            details.append(
                remarks
            )

        if details:
            parts.append(
                f"{sku}: " + " | ".join(details)
            )

    return " ; ".join(
        parts
    )


def file_lark_returns(
    context,
    *,
    order_id: str,
    returned_products: list[dict],
    return_case: dict | None,
    case_decision: dict | None,
    odoo_results: dict,
    progress_callback=None,
) -> list[dict]:
    """
    File exactly ONE Lark form per Odoo Transfer ID.

    Therefore:
        1 Odoo Transfer ID = 1 Lark filing

    Example:
        TC/IN/07674 contains:
            MLE05683_1
            MLE05696_1

        -> one Lark form
           SKU = MLE05683_1, MLE05696_1
           QTY = 2
           Transfer ID = TC/IN/07674

    Value uses the Shopee refund/order amount paid/refunded to the customer,
    NOT the individual SKU prices.
    """

    if not order_id:
        raise ValueError(
            "Order ID is required for Lark filing."
        )

    if not returned_products:
        raise ValueError(
            "No returned products are available for Lark filing."
        )

    if not return_case:
        raise ValueError(
            "Shopee return/refund data is required for Lark filing."
        )

    if not odoo_results:
        raise ValueError(
            "Odoo processing must complete before Lark filing."
        )

    transfers = odoo_results.get(
        "returns",
        [],
    )

    if not transfers:
        raise ValueError(
            "No Odoo Transfer IDs are available for Lark filing."
        )

    try:
        order_refund_value = float(
            return_case["refund_value"]
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            "Shopee refunded/order value is missing or invalid."
        ) from error

    if order_refund_value < 0:
        raise ValueError(
            "Shopee refunded/order value cannot be negative."
        )

    returned_pool = _build_returned_item_pool(
        returned_products
    )

    page = get_or_open_lark_page(
        context
    )
    page.bring_to_front()

    results = []

    for transfer_index, transfer in enumerate(
        transfers,
        start=1,
    ):
        transfer_id = str(
            transfer.get(
                "transfer_id",
                "",
            )
        ).strip()

        transfer_url = str(
            transfer.get(
                "transfer_url",
                "",
            )
        ).strip()

        if not transfer_id or not transfer_url:
            raise ValueError(
                f"Odoo Transfer #{transfer_index} is missing "
                "its Transfer ID or Transfer Link."
            )

        items = _take_items_for_transfer(
            transfer,
            returned_pool,
        )

        # Prefer the values recorded by Odoo's return group itself.
        decision = str(
            transfer.get(
                "decision",
                "",
            )
        ).strip()

        classification = str(
            transfer.get(
                "classification",
                "",
            )
        ).strip()

        status = str(
            transfer.get(
                "status",
                "",
            )
        ).strip()

        if not decision:
            decision = _shared_item_field(
                items,
                "decision",
                "Decision",
            )

        if not classification:
            classification = _shared_item_field(
                items,
                "classification",
                "Classification",
            )

        if not status:
            status = _shared_item_field(
                items,
                "status",
                "Status",
            )

        platform = _shared_item_field(
            items,
            "platform",
            "Platform",
            default="Shopee",
        ) or "Shopee"

        # One Lark form has one Grade field. For Unsealed transfers,
        # all items must therefore share the same Grade.
        grade = ""

        if classification == "Unsealed":
            grade = _shared_item_field(
                items,
                "grade",
                "Grade",
            )

            if not grade:
                raise ValueError(
                    f"Grade is required for Unsealed Transfer "
                    f"{transfer_id}."
                )

        sku_text = ", ".join(
            f"{str(item['sku']).strip()}_{int(item['quantity'])}"
            for item in items
        )

        total_quantity = sum(
            int(item["quantity"])
            for item in items
        )

        remarks = _combine_transfer_remarks(
            items
        )

        if progress_callback:
            progress_callback(
                (
                    f"Filing Lark Transfer "
                    f"{transfer_index}/{len(transfers)}: "
                    f"{transfer_id} | {sku_text}"
                )
            )

        result = file_lark_return(
            page=page,
            order_id=order_id,
            sku=sku_text,
            quantity=total_quantity,
            value=order_refund_value,
            classification=classification,
            status=status,
            decision=decision,
            platform=platform,
            transfer_id=transfer_id,
            transfer_link=transfer_url,
            remarks=remarks,
            grade=grade,
            progress_callback=progress_callback,
        )

        result["transfer_index"] = transfer_index
        result["items"] = [
            {
                "sku": str(item["sku"]).strip(),
                "quantity": int(item["quantity"]),
            }
            for item in items
        ]
        result["item_count"] = len(
            items
        )
        result["value_source"] = (
            "Shopee refunded/order value"
        )

        results.append(
            result
        )

    return results


__all__ = [
    "build_prefilled_lark_url",
    "get_or_open_lark_page",
    "file_lark_return",
    "file_lark_returns",
]
