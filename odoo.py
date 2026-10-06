import re

ODOO_TICKETS_URL = "https://makerlab.odoo.com/odoo/helpdesk/3/tickets"

DEFAULT_TIMEOUT = 30_000
SLOW_ODOO_TIMEOUT = 60_000
ODOO_COMMIT_BUFFER_MS = 700

_TICKET_URL_RE = re.compile(
    r".*/odoo/helpdesk/3/tickets/\d+(?:[/?#].*)?$"
)
_TRANSFER_ID_RE = re.compile(r"TC/IN/\d+")
_SKU_RE = re.compile(r"\[(MLE\d+)\]")

_RETURN_TABLE_JS = """
rows => rows.map(row => {
    const productCell = row.querySelector('td[name="product_id"]');
    const qtyCell = row.querySelector('td[name="quantity"]');
    const qtyInput = qtyCell?.querySelector('input');

    return {
        product:
            productCell?.getAttribute('data-tooltip') ||
            productCell?.textContent?.trim() ||
            "",
        quantity:
            qtyInput
                ? qtyInput.value
                : qtyCell?.textContent?.trim() || ""
    };
})
"""


def _text(value) -> str:
    return str(value or "").strip()


def _unique(values):
    return list(dict.fromkeys(
        value for value in (_text(v) for v in values) if value
    ))


def _progress(callback, message: str):
    if callback:
        callback(message)
    print(message)


def build_ticket_title(order_id: str, returned_products: list[dict]) -> str:
    """
    Build ORDER ID - SKU_QTY while combining duplicate SKU rows in the title
    only. The underlying item rows stay separate for different return routes.
    """
    if not returned_products:
        raise ValueError("At least one returned product is required.")

    quantities = {}
    order = []
    for item in returned_products:
        sku = _text(item["sku"])
        if sku not in quantities:
            quantities[sku] = 0
            order.append(sku)
        quantities[sku] += int(item["quantity"])

    return (
        f"{_text(order_id)} - "
        + ", ".join(f"{sku}_{quantities[sku]}" for sku in order)
    )


def get_or_open_odoo_page(context):
    for page in context.pages:
        if not page.is_closed() and "/odoo/helpdesk/3/tickets" in page.url:
            return page

    page = context.new_page()
    page.goto(
        ODOO_TICKETS_URL,
        wait_until="domcontentloaded",
        timeout=SLOW_ODOO_TIMEOUT,
    )
    return page


def _set_basic_ticket_fields(page, ticket_title: str):
    page.get_by_role("button", name="New").click()

    title = page.get_by_role("textbox", name="Ticket Title")
    title.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    title.fill(ticket_title)

    assigned_to = page.get_by_role("combobox", name="Assigned to")
    assigned_to.click()
    assigned_to.fill("Tech")
    page.get_by_role(
        "option",
        name="Technical Department",
        exact=True,
    ).click()

    customer = page.get_by_role("combobox", name="Customer")
    customer.click()
    customer.fill("Shop")
    page.get_by_role(
        "option",
        name="ECOMMERCE, SHOPEE",
        exact=True,
    ).click()


def _create_and_open_ticket(page, ticket_title: str) -> str:
    page.get_by_role("button", name="Add", exact=True).click()

    created = page.get_by_text(ticket_title, exact=True).first
    created.wait_for(state="visible", timeout=SLOW_ODOO_TIMEOUT)
    created.click()

    page.wait_for_url(_TICKET_URL_RE, timeout=SLOW_ODOO_TIMEOUT)
    page.get_by_role("combobox", name="Product?").wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )
    return page.url


def _select_product(page, sku: str):
    field = page.get_by_role("combobox", name="Product?")
    field.click()
    field.fill(sku)

    option = page.get_by_role(
        "option",
        name=re.compile(rf"^\[{re.escape(sku)}\]"),
    ).first
    option.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    option.click()


def _select_tags(page, tags: list[str]):
    tags = _unique(tags)
    if not tags:
        raise ValueError("At least one Odoo tag is required.")

    for tag in tags:
        field = page.get_by_role("combobox", name="Tags")
        field.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        field.click()
        field.fill(tag[:12])

        option = page.get_by_role("option", name=tag, exact=True)
        option.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        option.click()


def _set_urgent_priority(page):
    urgent = page.get_by_role("radio", name="Urgent")
    urgent.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    urgent.click()


def _get_return_dialog(page):
    dialog = page.get_by_role("dialog").last
    dialog.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return dialog


def _moves_table(dialog):
    table = dialog.locator('div[name="product_return_moves"]')
    table.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return table


def _return_rows(dialog):
    rows = _moves_table(dialog).locator("tbody > tr.o_data_row")
    rows.first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return rows


def _read_return_table(dialog) -> dict[str, float]:
    """
    One browser round-trip for the entire return table.
    Result: {SKU: quantity}
    """
    data = _return_rows(dialog).evaluate_all(_RETURN_TABLE_JS)
    result = {}

    for item in data:
        match = _SKU_RE.search(_text(item.get("product")))
        if not match:
            continue

        raw = _text(item.get("quantity")).replace(",", "") or "0"
        try:
            result[match.group(1)] = float(raw)
        except ValueError:
            result[match.group(1)] = 0.0

    return result


def _find_return_product_row(dialog, sku: str):
    """
    Locate the exact SKU using Odoo's stable product data-tooltip.
    """
    row = _moves_table(dialog).locator(
        (
            "tbody > tr.o_data_row:"
            f'has(td[name="product_id"][data-tooltip^="[{sku}]"])'
        )
    ).first
    row.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    tooltip = _text(
        row.locator('td[name="product_id"]').get_attribute("data-tooltip")
    )
    if not tooltip.startswith(f"[{sku}]"):
        raise ValueError(
            f"Odoo row safety check failed. "
            f"Expected SKU {sku}, found: {tooltip!r}"
        )
    return row


def _set_return_row_quantity(
    page,
    dialog,
    sku: str,
    quantity: int,
):
    """
    Activate and fill the exact quantity cell without coordinates, Ctrl+A,
    Tab, Enter, or click-away behavior.
    """
    for attempt in range(2):
        row = _find_return_product_row(dialog, sku)
        cell = row.locator('td[name="quantity"]')
        cell.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

        try:
            # Odoo may replace the clicked node immediately after the click.
            cell.click(force=True, timeout=1_500)
        except Exception:
            pass

        page.wait_for_timeout(200)

        row = _find_return_product_row(dialog, sku)
        qty_input = row.locator('td[name="quantity"] input').first

        try:
            qty_input.wait_for(state="visible", timeout=1_500)
        except Exception:
            if attempt == 0:
                continue
            raise RuntimeError(
                f"Odoo found and selected SKU {sku}, "
                "but its Quantity input did not enter edit mode."
            )

        qty_input.fill(str(quantity))
        actual = _text(qty_input.input_value())

        try:
            actual_number = float(actual)
        except ValueError as error:
            raise RuntimeError(
                f"Invalid quantity value for {sku}: {actual!r}"
            ) from error

        if actual_number != float(quantity):
            raise RuntimeError(
                f"Quantity verification failed for {sku}. "
                f"Expected {quantity}, got {actual!r}."
            )

        print(f"ODOO RETURN QTY SET: {sku} = {quantity}")
        return

    raise RuntimeError(f"Could not enter return quantity for {sku}.")


def _wait_for_return_skus(dialog, expected_skus) -> dict[str, float]:
    """
    Event-driven wait for every expected SKU. This replaces repeated full-table
    polling while preserving the protection against Odoo's progressive render.
    """
    expected = {_text(sku) for sku in expected_skus if _text(sku)}

    try:
        table = _moves_table(dialog)
        for sku in expected:
            table.locator(
                f'td[name="product_id"][data-tooltip^="[{sku}]"]'
            ).first.wait_for(
                state="attached",
                timeout=SLOW_ODOO_TIMEOUT,
            )
    except Exception as error:
        current = _read_return_table(dialog)
        missing = expected - set(current)
        raise RuntimeError(
            "These returned SKU(s) were not found in the Odoo Sales Order "
            "after waiting for the full Return table to load: "
            + ", ".join(sorted(missing or expected))
        ) from error

    current = _read_return_table(dialog)
    missing = expected - set(current)
    if missing:
        raise RuntimeError(
            "These returned SKU(s) were not found in the Odoo Sales Order: "
            + ", ".join(sorted(missing))
        )

    print("ODOO RETURN ITEMS READY:", ", ".join(sorted(current)))
    return current


def _verify_return_quantities(
    dialog,
    expected_by_sku: dict[str, int],
):
    """
    Final safety gate: target SKUs must equal requested quantities and every
    non-target SKU must remain zero.
    """
    current = _read_return_table(dialog)
    missing = set(expected_by_sku) - set(current)
    if missing:
        raise RuntimeError(
            "Safety stop: target SKU(s) not found in Odoo Return table: "
            + ", ".join(sorted(missing))
        )

    print("\nODOO RETURN PRE-SUBMIT CHECK:")
    for sku, actual in current.items():
        expected = float(expected_by_sku.get(sku, 0))
        print(f"{sku} | actual {actual} | expected {expected}")
        if actual != expected:
            raise RuntimeError(
                f"Safety stop: {sku} should return {expected:g}, "
                f"but Odoo currently shows {actual:g}. Return was NOT submitted."
            )


def _open_return_transfer(
    page,
    order_id: str,
    items: list[dict],
):
    if not items:
        raise ValueError("Return group contains no items.")

    desired = {}
    for item in items:
        sku = _text(item["sku"])
        desired[sku] = desired.get(sku, 0) + int(item["quantity"])

    button = page.get_by_role("button", name="Return", exact=True)
    button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    button.click()

    dialog = _get_return_dialog(page)

    sales_order = dialog.get_by_role("combobox", name="Sales Order")
    sales_order.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    sales_order.fill(order_id[-4:])

    order_option = page.get_by_role(
        "option",
        name=order_id,
        exact=True,
    )
    order_option.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    order_option.click()

    current = _wait_for_return_skus(dialog, desired)
    print("\nODOO RETURN TABLE BEFORE EDIT:")
    for sku, qty in current.items():
        print(f"{sku} | QTY {qty}")

    for sku, quantity in desired.items():
        print(f"SETTING ODOO RETURN: {sku} -> {quantity}")
        _set_return_row_quantity(page, dialog, sku, quantity)

    _verify_return_quantities(dialog, desired)

    create = dialog.locator('button[name="action_create_returns"]')
    create.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    create.click()


def _capture_transfer(page):
    heading = page.get_by_role("heading").get_by_text(_TRANSFER_ID_RE).first
    heading.wait_for(state="visible", timeout=SLOW_ODOO_TIMEOUT)

    heading_text = _text(heading.inner_text())
    match = _TRANSFER_ID_RE.search(heading_text)
    if not match:
        raise ValueError(
            f"Could not extract TC transfer ID from {heading_text!r}"
        )

    return {
        "transfer_id": match.group(0),
        "transfer_url": page.url,
        "heading": heading,
    }


def _click_validate(page):
    button = page.get_by_role(
        "button",
        name=re.compile(r"^Validate"),
    ).first
    button.wait_for(state="visible", timeout=SLOW_ODOO_TIMEOUT)
    button.click()


def _process_brand_new(page):
    destination = page.get_by_role(
        "combobox",
        name="Destination Location",
    )
    destination.wait_for(state="visible", timeout=SLOW_ODOO_TIMEOUT)
    destination.click()
    destination.fill("MNL/Stock")

    page.get_by_role(
        "option",
        name="MNL/Stock",
        exact=True,
    ).click()

    transfer = _capture_transfer(page)

    # Required by observed Odoo behavior so MNL/Stock commits before Validate.
    transfer["heading"].click()
    page.wait_for_timeout(ODOO_COMMIT_BUFFER_MS)
    _click_validate(page)

    return {
        "destination_location": "MNL/Stock",
        "qc_result": None,
        "transfer_id": transfer["transfer_id"],
        "transfer_url": transfer["transfer_url"],
        "validated": True,
    }


def _wait_for_next_qc_dialog(
    page,
    expected_skus: set[str],
    processed_skus: set[str],
):
    """
    Wait for the next automatically opened TECHNICAL RETURN QC dialog and
    identify its SKU from the title.
    """
    elapsed = 0
    poll_ms = 250

    while elapsed < SLOW_ODOO_TIMEOUT:
        dialogs = page.locator('div[role="dialog"]')
        for index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(index)
            if not dialog.is_visible():
                continue

            title = dialog.locator("h4.modal-title")
            if not title.count():
                continue

            title_text = _text(title.inner_text())
            if "TECHNICAL RETURN QC" not in title_text:
                continue

            match = _SKU_RE.search(title_text)
            if not match:
                continue

            sku = match.group(1)
            if sku in expected_skus and sku not in processed_skus:
                return dialog, sku, title_text

        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms

    remaining = sorted(expected_skus - processed_skus)
    raise RuntimeError(
        "Timed out waiting for the next Odoo QC dialog. "
        "Remaining SKU(s): "
        + ", ".join(remaining)
    )


def _process_open_box_or_defective(
    page,
    items: list[dict],
):
    if not items:
        raise ValueError(
            "Open Box / Defective QC requires at least one item."
        )

    route_by_classification = {
        "Unsealed": "TC/Stock/Open Box",
        "Defective": "TC/Defective",
    }
    item_by_sku = {}

    for item in items:
        sku = _text(item["sku"])
        classification = _text(item.get("classification"))
        try:
            qc_result = route_by_classification[classification]
        except KeyError as error:
            raise ValueError(
                f"Unsupported QC classification for {sku}: {classification}"
            ) from error

        item_by_sku[sku] = {
            "classification": classification,
            "qc_result": qc_result,
        }

    expected = set(item_by_sku)
    processed = set()
    qc_results = []
    transfer = _capture_transfer(page)

    _click_validate(page)

    while processed != expected:
        dialog, sku, title_text = _wait_for_next_qc_dialog(
            page,
            expected,
            processed,
        )
        route = item_by_sku[sku]["qc_result"]

        print(f"ODOO QC: {sku} -> FAIL -> {route}")
        print(f"QC DIALOG: {title_text}")

        fail = dialog.get_by_role("button", name="Fail", exact=True)
        fail.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        fail.click()

        option = page.get_by_text(route, exact=True).last
        option.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        option.click()

        confirm = page.get_by_role(
            "button",
            name="Confirm",
            exact=True,
        ).last
        confirm.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        confirm.click()

        processed.add(sku)
        qc_results.append({
            "sku": sku,
            "classification": item_by_sku[sku]["classification"],
            "qc_result": route,
        })

        # Small handoff buffer while Odoo closes this QC and opens the next.
        page.wait_for_timeout(350)

    return {
        "destination_location": None,
        "qc_result": (
            qc_results[0]["qc_result"]
            if len(qc_results) == 1
            else "Multiple"
        ),
        "qc_results": qc_results,
        "transfer_id": transfer["transfer_id"],
        "transfer_url": transfer["transfer_url"],
        "validated": True,
    }


def _return_group_key(item: dict):
    return (
        _text(item.get("decision")),
        _text(item.get("classification")),
        _text(item.get("status")),
    )


def _build_return_groups(items: list[dict]) -> list[dict]:
    groups_by_key = {}
    order = []

    for item in items:
        key = _return_group_key(item)
        if key not in groups_by_key:
            groups_by_key[key] = {
                "decision": key[0],
                "classification": key[1],
                "status": key[2],
                "items": [],
            }
            order.append(key)
        groups_by_key[key]["items"].append(item)

    return [groups_by_key[key] for key in order]


def create_odoo_tickets(
    context,
    order_id: str,
    returned_products: list[dict],
    case_decision: dict | None = None,
    progress_callback=None,
) -> dict:
    """
    Create one Helpdesk ticket for the Shopee order and one or more stock
    returns grouped by Decision + Classification + Status.
    """
    order_id = _text(order_id)
    if not order_id:
        raise ValueError("Order ID is required.")
    if not returned_products:
        raise ValueError("No returned products were found.")

    supported = {"New", "Unsealed", "Defective"}
    for item in returned_products:
        classification = _text(item.get("classification"))
        status = _text(item.get("status"))

        if classification not in supported:
            raise NotImplementedError(
                "Odoo stock-return route is not implemented for "
                f"{classification or 'blank classification'}."
            )
        if status != "Returned":
            raise NotImplementedError(
                "Odoo stock-return processing currently requires "
                "Status = Returned."
            )

    ticket_title = build_ticket_title(order_id, returned_products)
    first_sku = _text(returned_products[0]["sku"])
    tags = _unique(item.get("odoo_tag") for item in returned_products)

    page = get_or_open_odoo_page(context)
    page.bring_to_front()

    if (
        "/odoo/helpdesk/3/tickets" not in page.url
        or _TICKET_URL_RE.search(page.url)
    ):
        page.goto(
            ODOO_TICKETS_URL,
            wait_until="domcontentloaded",
            timeout=SLOW_ODOO_TIMEOUT,
        )

    page.get_by_role("button", name="New").wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )

    _progress(progress_callback, f"Creating one Odoo ticket: {ticket_title}")
    _set_basic_ticket_fields(page, ticket_title)

    _progress(progress_callback, "Saving new Odoo ticket...")
    ticket_url = _create_and_open_ticket(page, ticket_title)

    _progress(
        progress_callback,
        f"Selecting first returned product: {first_sku}",
    )
    _select_product(page, first_sku)

    _progress(
        progress_callback,
        "Adding Odoo tag(s): " + ", ".join(tags),
    )
    _select_tags(page, tags)

    _progress(progress_callback, "Setting priority to Urgent...")
    _set_urgent_priority(page)

    groups = _build_return_groups(returned_products)
    return_results = []

    for index, group in enumerate(groups, start=1):
        if index > 1:
            _progress(
                progress_callback,
                f"Returning to Helpdesk ticket for Return #{index}...",
            )
            page.goto(
                ticket_url,
                wait_until="domcontentloaded",
                timeout=SLOW_ODOO_TIMEOUT,
            )
            page.get_by_role(
                "button",
                name="Return",
                exact=True,
            ).wait_for(
                state="visible",
                timeout=SLOW_ODOO_TIMEOUT,
            )

        item_text = ", ".join(
            f"{_text(item['sku'])}_{int(item['quantity'])}"
            for item in group["items"]
        )
        _progress(
            progress_callback,
            f"Creating Return #{index}: {item_text} | "
            f"{group['classification']} | {group['decision']}",
        )

        _open_return_transfer(page, order_id, group["items"])

        if group["classification"] == "New":
            stock_result = _process_brand_new(page)
        else:
            stock_result = _process_open_box_or_defective(
                page,
                group["items"],
            )

        return_results.append({
            "return_index": index,
            "decision": group["decision"],
            "classification": group["classification"],
            "status": group["status"],
            "items": [
                {
                    "sku": _text(item["sku"]),
                    "quantity": int(item["quantity"]),
                }
                for item in group["items"]
            ],
            **stock_result,
        })

        _progress(
            progress_callback,
            f"Return #{index} completed: {stock_result['transfer_id']}",
        )

    return {
        "ticket_title": ticket_title,
        "ticket_url": ticket_url,
        "product_sku": first_sku,
        "tags": tags,
        "returns": return_results,
    }


__all__ = [
    "build_ticket_title",
    "get_or_open_odoo_page",
    "create_odoo_tickets",
]
