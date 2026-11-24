import re
import time
import copy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, parse_qs

ODOO_TICKETS_URL = "https://makerlab.odoo.com/odoo/helpdesk/3/tickets"

DEFAULT_TIMEOUT = 30_000
SLOW_ODOO_TIMEOUT = 60_000
ODOO_COMMIT_BUFFER_MS = 700
# Return and two-stage validation policies, November 2026.
# Only for the exact Odoo "Zero Demand Warning" after a verified return.
# Keep the zero-demand lines; never click Remove lines automatically.
ZERO_DEMAND_WARNING_ACTION = "keep_lines"
# Optional: enter the EXACT warehouse employee/department names shown in
# Odoo's pending To Do activity if the task contains no "warehouse" text.
# Never treat an unrelated, generic To Do as return/warehouse handoff.
WAREHOUSE_PERSONNEL_NAMES: tuple[str, ...] = ()
NEW_STOCK_DESTINATIONS = ("MNL/Stock", "BLC/Stock")


def _validated_new_stock_destination(value) -> str:
    value = _text(value)
    if value not in NEW_STOCK_DESTINATIONS:
        raise ValueError(f"Unsupported New-stock destination: {value!r}")
    return value


_TICKET_URL_RE = re.compile(
    r".*/odoo/helpdesk/3/tickets/\d+(?:[/?#].*)?$"
)
_TRANSFER_ID_RE = re.compile(r"TC/IN/\d+")
_SKU_RE = re.compile(r"\[([A-Za-z0-9_+.-]+)\]")

ODOO_CUSTOMER_BY_PLATFORM = {
    "Shopee": "ECOMMERCE, SHOPEE",
    "Lazada": "ECOMMERCE, LAZADA",
    "TikTok": "ECOMMERCE, TIKTOK",
}


class OdooReturnNotReadyError(RuntimeError):
    """Safe-to-retry failure before Odoo creates the stock return."""


class OdooReturnOpenUncertainError(RuntimeError):
    """Unexpected result while opening Return; requires human reconciliation."""


class OdooWorkflowPausedError(RuntimeError):
    """Carries a saved Helpdesk-ticket checkpoint for a later retry."""

    def __init__(self, message: str, checkpoint: dict):
        super().__init__(message)
        self.checkpoint = checkpoint

_OPERATIONS_TABLE_JS = """
rows => rows.map(row => {
    const productCell = row.querySelector('td[name="product_id"]');
    const productNode = productCell?.querySelector('[data-tooltip^="["]');
    const product =
        productNode?.getAttribute('data-tooltip') ||
        productNode?.getAttribute('title') ||
        productCell?.getAttribute('data-tooltip') ||
        productCell?.textContent?.trim() || '';

    const demandCell = row.querySelector('td[name="product_uom_qty"]');
    const editor = demandCell?.querySelector('input:not([type="hidden"])');
    const demand = editor ? editor.value : demandCell?.textContent?.trim() || '';
    return {
        product: product.trim(),
        quantity: String(demand).trim(),
        row_id: row.getAttribute('data-id') || ''
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


def _checkpoint(callback, checkpoint: dict, event: str):
    """Require the caller to durably save the state before continuing Odoo."""
    if callback:
        callback(checkpoint, event)


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


def _set_basic_ticket_fields(page, ticket_title: str, platform: str = "Shopee"):
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

    platform = _text(platform) or "Shopee"
    customer_name = ODOO_CUSTOMER_BY_PLATFORM.get(
        platform,
        f"ECOMMERCE, {platform.upper()}",
    )

    customer = page.get_by_role("combobox", name="Customer")
    customer.click()
    customer.fill("Shop" if platform == "Shopee" else platform[:12])
    option = page.get_by_role(
        "option",
        name=customer_name,
        exact=True,
    )
    try:
        option.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        option.click()
    except Exception as error:
        raise RuntimeError(
            f"Odoo customer {customer_name!r} was not found for platform "
            f"{platform!r}. Update ODOO_CUSTOMER_BY_PLATFORM in odoo.py if "
            "your Odoo customer name is different."
        ) from error


def _create_and_open_ticket(page, ticket_title: str, on_created=None) -> str:
    page.get_by_role("button", name="Add", exact=True).click()

    created = page.get_by_text(ticket_title, exact=True).first
    created.wait_for(state="visible", timeout=SLOW_ODOO_TIMEOUT)
    created.click()

    page.wait_for_url(_TICKET_URL_RE, timeout=SLOW_ODOO_TIMEOUT)
    # The ticket is confirmed here. Save its URL BEFORE attempting any
    # product/tag/priority work: those selectors can time out after creation.
    if on_created:
        on_created(page.url)
    return page.url


def _product_input(page):
    """Odoo's product many2one input, independent of its visible label."""
    return page.locator(
        'div[name="product_id"] input[role="combobox"]'
    ).first


def _select_product(page, sku: str):
    """
    Select the exact SKU, not the first option containing the SKU text.

    New Odoo dropdown format (Nov 2026):
        <a role="option">Product description <span class="text-primary fw-bold">
            MLE04875</span></a>

    Older Odoo format:
        <a role="option">[MLE04875] Product description</a>

    In both cases, the "Create <SKU>" action must never be selected.
    """
    sku = _text(sku)
    if not sku:
        raise ValueError("Cannot select an empty Odoo product SKU.")

    field = _product_input(page)
    field.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    field.click()
    field.fill(sku)

    options = page.locator('div[name="product_id"] a[role="option"]')

    # Current Odoo: the product name comes first and the exact SKU is shown
    # inside a dedicated bold span. This excludes Create/Search-more entries.
    exact_sku_badge = page.locator(
        "span.text-primary.fw-bold"
    ).filter(
        has_text=re.compile(rf"^\s*{re.escape(sku)}\s*$", re.IGNORECASE)
    )
    current_option = options.filter(has=exact_sku_badge)

    # Compatibility with Odoo's older [SKU] Product name display.
    older_option = options.filter(
        has_text=re.compile(
            rf"^\s*\[{re.escape(sku)}\](?:\s|$)",
            re.IGNORECASE,
        )
    )

    matching = current_option.or_(older_option)
    try:
        matching.first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    except Exception as error:
        raise RuntimeError(
            f"Odoo could not find an existing product with exact SKU {sku}. "
            "The Helpdesk ticket may already have been created. Do not "
            "restart the full submission without checking the existing "
            f"ticket at {page.url}. The processor did NOT select a "
            "'Create' option."
        ) from error

    matches = matching.count()
    if matches != 1:
        raise RuntimeError(
            f"Odoo returned {matches} product options for exact SKU {sku}. "
            "Product selection stopped to avoid linking the wrong item. "
            f"Check the existing Helpdesk ticket at {page.url}."
        )

    selected_label = matching.first.inner_text().strip()
    matching.first.click()
    print(f"ODOO PRODUCT SELECTED: {sku} | {selected_label}")


def _select_tags(page, tags: list[str]):
    tags = _unique(tags)
    if not tags:
        raise ValueError("At least one Odoo tag is required.")

    for tag in tags:
        # A recovery may reopen a ticket after some tags were already saved.
        # Do not add a second copy of an existing tag.
        widget = page.locator('div[name="tag_ids"]').first
        if widget.count():
            selected = widget.locator('.o_tag, .badge, .o_tag_badge_text')
            if any(
                _text(value).casefold() == tag.casefold()
                for value in selected.all_inner_texts()
            ):
                continue
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
    if urgent.get_attribute("aria-checked") != "true":
        urgent.click()


_RETURN_TITLE_RE = re.compile(r"^\s*Return\s*$", re.IGNORECASE)


def _visible_return_dialog(page):
    """Find specifically the Odoo *Return* modal (not an unrelated dialog).

    Odoo's modal-content retains its fields even when a responsive layout
    changes the ARIA role on the surrounding modal. Use the heading and exact
    Sales Order + Delivery fields rather than `get_by_role('dialog').last`.
    """
    title = page.locator("h4.modal-title").filter(has_text=_RETURN_TITLE_RE)
    candidates = (
        page.locator(".modal-content:visible").filter(has=title),
        page.get_by_role("dialog").filter(has=title),
    )
    for candidate in candidates:
        count = candidate.count()
        for i in range(count - 1, -1, -1):
            item = candidate.nth(i)
            if not item.is_visible():
                continue
            if (
                item.locator('div[name="sale_order_id"] input').count()
                and item.locator('div[name="picking_id"] input').count()
            ):
                return item
    return None


def _get_return_dialog(page, timeout_ms=DEFAULT_TIMEOUT):
    """Wait for an actual Return wizard, irrespective of its ARIA container."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        dialog = _visible_return_dialog(page)
        if dialog is not None:
            return dialog
        page.wait_for_timeout(200)
    raise TimeoutError(
        "The Odoo Return modal did not appear after clicking the Helpdesk "
        "Return action (neither modal-content nor role=dialog was visible)."
    )


def _click_helpdesk_return_action(page):
    """Open the ticket Return action in wide OR Odoo's adaptive layout.

    On compact browser windows, Odoo moves Return into the status bar's
    'More' overflow. Never click the Returns smart button or stock Return All.
    This function only opens the Return *wizard*; it does not create a TC/IN.
    """
    statusbar = page.locator(".o_form_statusbar").first
    if not statusbar.count():
        raise OdooReturnNotReadyError(
            "The Helpdesk ticket status bar is not available."
        )

    direct = statusbar.get_by_role("button", name="Return", exact=True)
    for index in range(direct.count()):
        button = direct.nth(index)
        if button.is_visible() and button.is_enabled():
            button.click(timeout=DEFAULT_TIMEOUT)
            print("ODOO RETURN: opened direct ticket Return action")
            return

    # Screenshot/HTML on Nov 10: only Refund and a statusbar 'More' button
    # remain in the ticket DOM when responsive overflow is active.
    more = statusbar.locator('button[title="More"]').first
    if not more.count() or not more.is_visible():
        raise OdooReturnNotReadyError(
            "Odoo ticket has no visible Return action and no responsive "
            "More menu. The first/next stock return was NOT submitted."
        )
    more.click(timeout=DEFAULT_TIMEOUT)

    # Odoo may render the dropdown in an overlay outside the statusbar.
    # Search only a VISIBLE dropdown, never the ticket's smart 'Returns' button.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        overlays = page.locator(
            ".o-dropdown--menu:visible, .dropdown-menu:visible, "
            "[role='menu']:visible"
        )
        choices = overlays.get_by_text("Return", exact=True)
        for index in range(choices.count()):
            choice = choices.nth(index)
            if choice.is_visible():
                choice.click(timeout=DEFAULT_TIMEOUT)
                print("ODOO RETURN: opened Return via responsive More menu")
                return
        page.wait_for_timeout(150)
    raise OdooReturnNotReadyError(
        "The responsive More menu opened, but it has no visible Return "
        "action. No draft transfer was created by this attempt."
    )


def _open_helpdesk_return_dialog(page):
    """Handle a transient Odoo action rerender before creating any stock move.

    The Helpdesk Return trigger is pre-creation. We retry its wizard opening
    once after a clean ticket navigation, never the irreversible modal Return
    action. If Odoo unexpectedly navigates away, stop for manual review.
    """
    ticket_url = page.url
    if not _TICKET_URL_RE.fullmatch(ticket_url):
        raise OdooReturnOpenUncertainError(
            "Cannot open Return: current page is not a verified Helpdesk "
            f"ticket URL: {ticket_url!r}."
        )

    for attempt in range(2):
        # A delayed action may already have opened the wizard. Don't click twice.
        existing = _visible_return_dialog(page)
        if existing is not None:
            return existing
        _click_helpdesk_return_action(page)
        try:
            return _get_return_dialog(
                page, timeout_ms=15_000 if attempt == 0 else DEFAULT_TIMEOUT
            )
        except TimeoutError as error:
            # A post-click notification or unexpected page means we do not
            # know the outcome. Do not reload, retry, or assume it's safe.
            active_notices = page.locator(
                '.o_notification_manager .o_notification:visible, '
                '[role="alert"]:visible'
            )
            notices = [value.strip() for value in active_notices.all_inner_texts()
                       if value.strip()]
            other_dialogs = [value.strip() for value in page.locator(
                '.modal-content:visible h4.modal-title'
            ).all_inner_texts() if value.strip()]
            if notices or other_dialogs or not _TICKET_URL_RE.fullmatch(page.url):
                raise OdooReturnOpenUncertainError(
                    "Odoo did not open the expected Return wizard. "
                    f"Page: {page.url!r}; notices: {notices!r}; "
                    f"other dialogs: {other_dialogs!r}. "
                    "Manual review required; do NOT create another return."
                ) from error
            if attempt == 0:
                print("ODOO RETURN: wizard absent after ticket action; "
                      "reloading the same ticket and retrying its pre-create action once")
                page.goto(ticket_url, wait_until="domcontentloaded",
                          timeout=SLOW_ODOO_TIMEOUT)
                # Load/render complete before triggering Odoo's responsive menu.
                page.locator(".o_form_statusbar").wait_for(
                    state="visible", timeout=SLOW_ODOO_TIMEOUT
                )
                continue
            raise OdooReturnNotReadyError(
                "Odoo did not open the Return wizard after two attempts on "
                "the saved Helpdesk ticket. The wizard's irreversible Return "
                "action was NOT clicked, so the case is kept pending for "
                "inspection and safe retry."
            ) from error

    raise AssertionError("Unreachable Return wizard retry state")


def _requested_return_quantities(items: list[dict]) -> dict[str, int]:
    """Validate and combine exact SKUs BEFORE an Odoo Return is created."""
    if not items:
        raise ValueError("Return group contains no items.")
    result = {}
    for item in items:
        sku = _text(item.get("sku"))
        if not re.fullmatch(r"[A-Za-z0-9_+.-]+", sku):
            raise ValueError(f"Invalid Odoo return SKU: {sku!r}")
        try:
            qty = int(item["quantity"])
            if Decimal(str(item["quantity"])) != qty:
                raise ValueError()
        except (ValueError, TypeError, KeyError, InvalidOperation) as error:
            raise ValueError(f"Invalid return QTY for {sku!r}.") from error
        if qty <= 0:
            raise ValueError(f"Return QTY for {sku} must be greater than zero.")
        result[sku] = result.get(sku, 0) + qty
    return result


def _operations_table(page):
    """NEW Odoo: Operations lives on the stock.picking form, not the wizard."""
    table = page.locator('div[name="move_ids"]')
    table.wait_for(state="visible", timeout=SLOW_ODOO_TIMEOUT)
    return table


def _operation_rows(page, *, allow_empty=False):
    """Locate Odoo stock.move rows even while OWL is editing a selected row.

    Odoo can temporarily change a row's classes while an inline Demand input
    is active. A stable data-id is present on the captured stock.move rows;
    selecting by this identity avoids losing the row during the rerender.
    """
    rows = _operations_table(page).locator(
        'table.o_list_table tbody tr[data-id]'
    )
    if not allow_empty:
        rows.first.wait_for(state="visible", timeout=SLOW_ODOO_TIMEOUT)
    return rows


def _read_operation_rows(page, *, allow_empty=False,
                         warning_dialog_open=False) -> list[dict]:
    """Read product identities and Demand without depending on modal focus.

    During Zero Demand Warning, Bootstrap/Odoo can make the stock form inert
    to accessible locators. The table remains in the DOM, so read it directly
    without a 60-second background-element visibility wait.
    """
    if warning_dialog_open:
        raw = page.locator(
            'div[name="move_ids"] table.o_list_table tbody tr[data-id]'
        ).evaluate_all(_OPERATIONS_TABLE_JS)
        if not raw:
            raise RuntimeError(
                'Zero Demand Warning is open, but the stock Operations rows '
                'cannot be read. Manual Review required; no action taken.'
            )
    else:
        raw = _operation_rows(page, allow_empty=allow_empty).evaluate_all(
            _OPERATIONS_TABLE_JS
        )
    result = []
    for line in raw:
        title = _text(line.get("product"))
        match = _SKU_RE.match(title)
        sku = match.group(1) if match else ""
        quantity_text = _text(line.get("quantity")).replace(",", "") or "0"
        try:
            qty = Decimal(quantity_text)
            if not qty.is_finite() or qty < 0:
                raise InvalidOperation()
        except InvalidOperation as error:
            raise RuntimeError(
                f"Odoo Operations has an invalid Demand for {title!r}: "
                f"{quantity_text!r}. Validation stopped."
            ) from error
        result.append({
            "sku": sku,
            "product": title,
            "quantity": qty,
            "row_id": _text(line.get("row_id")),
        })
    return result


def _wait_for_operation_skus(page, expected_skus) -> list[dict]:
    """Wait until all target SKUs are visible and row identities stabilize."""
    required = set(expected_skus)
    deadline = time.monotonic() + SLOW_ODOO_TIMEOUT / 1000.0
    signature = None
    stable = 0
    last = []

    while time.monotonic() < deadline:
        last = _read_operation_rows(page)
        current = {row["sku"] for row in last if row["sku"]}
        current_signature = tuple(
            (row["row_id"], row["sku"]) for row in last
        )
        if required.issubset(current):
            stable = stable + 1 if current_signature == signature else 1
            if stable >= 3:
                return last
        else:
            stable = 0
        signature = current_signature
        page.wait_for_timeout(250)

    missing = sorted(required - {row["sku"] for row in last})
    raise RuntimeError(
        "Odoo draft transfer already exists, but these SKU(s) are missing "
        "from Operations: " + ", ".join(missing or sorted(required))
        + ". Do NOT create a second Return."
    )


def _operation_row_by_id(page, row_id: str):
    """Find the one existing row by its Odoo data-id (not screen coordinates)."""
    if not row_id or not re.fullmatch(r"[a-zA-Z0-9_.:-]+", row_id):
        raise RuntimeError(
            "Odoo's Operations row has an unexpected/missing data-id; "
            "manual review is required before validation."
        )
    row = _operations_table(page).locator(
        f'table.o_list_table tbody tr[data-id="{row_id}"]'
    )
    return row


def _find_operation_row(page, sku: str, known_row_id: str = ""):
    """Find exactly one SKU row, also surviving an Odoo edit-mode rerender.

    The product SKU is embedded in the nested span[data-tooltip], NOT the td's
    data-tooltip. In edit mode that span can disappear temporarily. Once an
    exact SKU has been verified, the saved data-id keeps the target stable.

    If an Odoo rerender changes both the row ID and removes the SKU, we stop
    rather than guessing which row should receive the stock quantity.
    """
    sku = _text(sku)
    deadline = time.monotonic() + 6.0
    last_seen = []

    while time.monotonic() < deadline:
        last_seen = _read_operation_rows(page)
        exact = [row for row in last_seen if row["sku"] == sku]
        if len(exact) > 1:
            raise RuntimeError(
                f"Multiple Odoo Operations rows show SKU {sku}; "
                "manual quantity allocation is required."
            )

        # Prefer the confirmed row's data-id while an inline editor hides the
        # nested product display span. Never use an index or unrelated SKU.
        candidate = None
        if known_row_id:
            by_id = [r for r in last_seen if r["row_id"] == known_row_id]
            if len(by_id) > 1:
                raise RuntimeError(f"Duplicate Odoo row data-id {known_row_id!r}.")
            if by_id:
                if by_id[0]["sku"] not in ("", sku):
                    raise RuntimeError(
                        f"Odoo row {known_row_id!r} changed product from "
                        f"{sku!r} to {by_id[0]['sku']!r}; validation blocked."
                    )
                candidate = by_id[0]
        if candidate is None and len(exact) == 1:
            candidate = exact[0]

        if candidate is not None:
            row = _operation_row_by_id(page, candidate["row_id"])
            if row.count() == 1:
                return row
        page.wait_for_timeout(200)

    observed = [
        f"{r['sku'] or '?'} ({r['row_id'] or 'no-id'})"
        for r in last_seen
    ]
    raise RuntimeError(
        f"Expected one Operations row for exact SKU {sku!r}, but Odoo "
        "changed the row during inline editing. "
        f"Currently visible rows: {', '.join(observed) or 'none'}. "
        "The draft transfer exists; do not click Return again. "
        "Manual review required; no validation performed."
    )


def _transfer_heading(page):
    return page.get_by_role("heading").get_by_text(_TRANSFER_ID_RE).first


def _edit_operation_demand(page, sku: str, quantity: int):
    """Edit Demand on one verified stock.move row, surviving Odoo rerenders."""
    wanted = Decimal(quantity)
    initial_row = _find_operation_row(page, sku)
    # This row ID was verified while its bracketed SKU was visible.
    known_row_id = _text(initial_row.get_attribute("data-id"))

    for attempt in range(4):
        row = _find_operation_row(page, sku, known_row_id=known_row_id)
        # Odoo sometimes regenerates a row while retaining the exact SKU.
        known_row_id = _text(row.get_attribute("data-id")) or known_row_id
        cell = row.locator('td[name="product_uom_qty"]')
        cell.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

        editor = cell.locator('input:not([type="hidden"])').first
        try:
            editing = editor.count() == 1 and editor.is_visible()
        except Exception:
            editing = False

        if not editing:
            try:
                if attempt == 0:
                    cell.click(timeout=1_500)
                elif attempt == 1:
                    cell.click(force=True, timeout=1_500)
                else:
                    cell.dblclick(timeout=1_500)
            except Exception:
                # Only harmless if a reacquired editor is actually visible.
                # OWL often detaches the clicked cell as it activates edit mode.
                pass
            page.wait_for_timeout(120)
            # Reacquire by data-id, even if Odoo hides product data-tooltip.
            row = _find_operation_row(page, sku, known_row_id=known_row_id)
            known_row_id = _text(row.get_attribute("data-id")) or known_row_id
            editor = row.locator(
                'td[name="product_uom_qty"] input:not([type="hidden"])'
            ).first

        try:
            editor.wait_for(state="visible", timeout=1_500)
        except Exception:
            continue

        editor.fill(str(quantity))
        try:
            actual = Decimal(_text(editor.input_value()))
        except InvalidOperation as error:
            raise RuntimeError(f"Invalid Odoo Demand editor for {sku}.") from error
        if actual != wanted:
            raise RuntimeError(
                f"Demand editor mismatch for {sku}: expected {wanted}, got {actual}."
            )

        # Blur on the transfer heading so Odoo commits the inline float input.
        _transfer_heading(page).click(timeout=DEFAULT_TIMEOUT)
        for _ in range(15):
            current = [r for r in _read_operation_rows(page) if r["sku"] == sku]
            if len(current) == 1 and current[0]["quantity"] == wanted:
                print(f"ODOO DEMAND SET: {sku} = {quantity}")
                return
            page.wait_for_timeout(200)
        raise RuntimeError(
            f"Odoo Demand for {sku} did not commit. "
            "The draft transfer exists; do not Validate or create another Return."
        )

    raise RuntimeError(
        f"Could not activate the Demand editor for {sku} after four "
        "attempts. Existing draft must be reviewed; do not create another Return."
    )

def _save_operation_demands(page):
    """Wait for stock.picking form save; never click Validate in this helper."""
    _transfer_heading(page).click(timeout=DEFAULT_TIMEOUT)
    save = page.locator('button.o_form_button_save:visible').first
    if save.count() and save.is_enabled():
        save.click(timeout=DEFAULT_TIMEOUT)
    page.locator('.o_form_renderer.o_form_saved').first.wait_for(
        state="visible", timeout=SLOW_ODOO_TIMEOUT
    )


def _verify_operation_demands(page, expected: dict[str, int],
                              *, warning_dialog_open=False):
    """Fail closed for non-target SKUs, ambiguous rows or wrong saved Demand."""
    # Reading an open inline editor is not evidence that Odoo committed it.
    open_editors = page.locator(
        'div[name="move_ids"] td[name="product_uom_qty"] input:visible'
    )
    if open_editors.count():
        raise RuntimeError(
            "Odoo Demand is still being edited. The stock transfer was not "
            "confirmed saved, so Validation is blocked."
        )
    data = _read_operation_rows(
        page, warning_dialog_open=warning_dialog_open
    )
    counts = {}
    for row in data:
        sku = row["sku"]
        qty = row["quantity"]
        if sku:
            counts[sku] = counts.get(sku, 0) + 1
        if not sku and qty:
            raise RuntimeError(
                f"Nonzero Demand {qty} on unidentified Odoo product "
                f"{row['product']!r}. Validation blocked."
            )
        wanted = Decimal(expected.get(sku, 0))
        if qty != wanted:
            raise RuntimeError(
                f"Unsafe Odoo Demand for {sku or row['product']!r}: "
                f"expected {wanted}, got {qty}. Validation blocked."
            )
    duplicate = sorted(sku for sku, count in counts.items() if count != 1)
    if duplicate:
        raise RuntimeError(
            "Duplicate SKU rows in Odoo Operations need manual allocation: "
            + ", ".join(duplicate)
        )
    missing = sorted(set(expected) - set(counts))
    if missing:
        raise RuntimeError(
            "Requested SKU(s) missing from Odoo Operations: "
            + ", ".join(missing)
        )
    print("ODOO TRANSFER DEMANDS VERIFIED:", expected)



# Odoo can create a completely EMPTY stock.picking when the Return wizard's
# Delivery to Return field is blank. This is an alternate stock-move creation
# path, not a reason to recreate the Helpdesk Return.
EMPTY_DELIVERY_OPERATION_TYPE = "TECHNICAL: Receipts"
EMPTY_DELIVERY_STAGING_LOCATION = "TC/Stock"


def _read_many2one_selection(field) -> str:
    """Read a selected many2one without trusting the input alone."""
    editor = field.locator('input[role="combobox"]').first
    if editor.count():
        value = _text(editor.input_value(timeout=2_000))
        if value:
            return value
    # Older Odoo sometimes changes an autocomplete to a display span.
    displayed = field.locator('.o_many2one span[data-tooltip]').first
    if displayed.count():
        value = _text(displayed.get_attribute('data-tooltip'))
        if value:
            return value
    return _text(field.inner_text(timeout=2_000))


def _select_required_transfer_field(page, field_name: str, value: str,
                                     search: str | None = None):
    """Set an empty Odoo field using ONE exact existing option; never create.

    A prepopulated value must already match. If a saved field differs, stop
    instead of silently changing the receiving customer or operation type.
    """
    field = page.locator(f'div[name="{field_name}"].o_field_widget').first
    field.wait_for(state='visible', timeout=DEFAULT_TIMEOUT)
    actual = _read_many2one_selection(field)
    if actual:
        if ' '.join(actual.split()).casefold() != ' '.join(value.split()).casefold():
            raise RuntimeError(
                f'Existing Odoo {field_name} is {actual!r}, expected {value!r}. '
                'The TC/IN already exists; correct it manually, not by Return.'
            )
        return

    editor = field.locator('input[role="combobox"]').first
    editor.wait_for(state='visible', timeout=DEFAULT_TIMEOUT)
    editor.fill(search or value)
    options = page.get_by_role('option', name=value, exact=True)
    try:
        options.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT)
    except Exception as exc:
        raise RuntimeError(
            f'Odoo has no selectable existing {field_name} option {value!r}. '
            'TC/IN was already created; do not click Return again.'
        ) from exc
    if options.count() != 1:
        raise RuntimeError(
            f'Odoo has {options.count()} matching options for {field_name} '
            f'{value!r}. Manual Review required.'
        )
    options.click(timeout=DEFAULT_TIMEOUT)
    # Odoo updates the many2one asynchronously. Avoid racing a dependent field.
    deadline = time.monotonic() + DEFAULT_TIMEOUT / 1000
    while time.monotonic() < deadline:
        if ' '.join(_read_many2one_selection(field).split()).casefold() == (
            ' '.join(value.split()).casefold()
        ):
            return
        page.wait_for_timeout(150)
    raise RuntimeError(
        f'Odoo did not confirm selected {field_name} {value!r}. '
        'No stock validation was attempted.'
    )


def _ensure_deliveryless_transfer_header(page, order_id: str,
                                         platform: str):
    """Fill fields missing in a TC/IN made without a source Delivery.

    The New classification switches TC/Stock to configured MNL/Stock or
    BLC/Stock in _process_brand_new, *after* rows have been verified.
    """
    customer = ODOO_CUSTOMER_BY_PLATFORM.get(
        _text(platform) or 'Shopee',
        'ECOMMERCE, ' + (_text(platform) or 'Shopee').upper(),
    )
    _select_required_transfer_field(
        page, 'partner_id', customer, search=(
            'Shop' if platform == 'Shopee' else _text(platform)[:12]
        )
    )
    _select_required_transfer_field(
        page, 'picking_type_id', EMPTY_DELIVERY_OPERATION_TYPE,
        search='TECHNICAL',
    )
    _select_required_transfer_field(
        page, 'location_dest_id', EMPTY_DELIVERY_STAGING_LOCATION,
        search=EMPTY_DELIVERY_STAGING_LOCATION,
    )

    origin = page.locator('div[name="origin"] input.o_input').first
    origin.wait_for(state='visible', timeout=DEFAULT_TIMEOUT)
    if not _text(origin.input_value()):
        # There is no delivery number to reference. Keep the marketplace
        # sales order visible for audit without inventing a BLC/OUT number.
        origin.fill(f'Return of {order_id}')
        _transfer_heading(page).click(timeout=DEFAULT_TIMEOUT)
    print('ODOO NO-DELIVERY HEADER SET:', customer,
          EMPTY_DELIVERY_OPERATION_TYPE, EMPTY_DELIVERY_STAGING_LOCATION)


def _select_exact_stock_product_option(page, sku: str):
    """Select only an existing product with a uniquely identified exact SKU.

    Compatible with Odoo's [SKU] Product and Product <b>SKU</b> lists.
    Never select Create/Edit or any option where SKU is only a substring.
    """
    sku = _text(sku)
    token = re.compile(rf'^\s*\[{re.escape(sku)}\](?:\s|$)', re.I)
    exact_badge = re.compile(rf'^\s*{re.escape(sku)}\s*$', re.I)
    deadline = time.monotonic() + DEFAULT_TIMEOUT / 1000.0
    while time.monotonic() < deadline:
        options = page.get_by_role('option')
        candidates = []
        for idx in range(options.count()):
            option = options.nth(idx)
            if not option.is_visible():
                continue
            text = _text(option.inner_text())
            if re.search(r'^\s*(?:create(?: and edit)?|search more)(?:\s|$)', text, re.I):
                continue
            badge = option.locator('span.text-primary.fw-bold')
            badge_match = any(
                exact_badge.fullmatch(_text(badge.nth(k).inner_text()))
                for k in range(badge.count())
            )
            if token.search(text) or badge_match:
                candidates.append(option)
        if len(candidates) > 1:
            raise RuntimeError(
                f'Odoo returned multiple selectable product options for {sku}. '
                'The existing TC/IN requires Manual Review.'
            )
        if len(candidates) == 1:
            candidates[0].click(timeout=DEFAULT_TIMEOUT)
            return
        page.wait_for_timeout(200)
    raise RuntimeError(
        f'Odoo did not suggest an existing exact product {sku}. '
        'The TC/IN was already created; do not create a second Return.'
    )


def _add_missing_stock_move(page, sku: str, quantity: int):
    """Create ONE missing stock.move using Odoo Add a Product UI."""
    # If a previous interrupted attempt already saved this row, reuse it.
    current = _read_operation_rows(page, allow_empty=True)
    already = [r for r in current if r['sku'] == sku]
    if len(already) == 1:
        return
    if len(already) > 1:
        raise RuntimeError(f'Odoo has duplicate existing product rows for {sku}.')
    if any(not r['sku'] for r in current):
        raise RuntimeError(
            'Odoo Operations has an unidentified or unfinished product row. '
            'Manual Review required rather than creating another row.'
        )
    add = _operations_table(page).locator(
        '.o_field_x2many_list_row_add button'
    ).filter(has_text='Add a Product')
    if add.count() != 1:
        raise RuntimeError(
            'Odoo Add a Product action is missing or ambiguous. '
            'Existing transfer requires manual reconciliation.'
        )
    add.click(timeout=DEFAULT_TIMEOUT)
    product_editor = _operations_table(page).locator(
        'table.o_list_table tbody tr[data-id] '
        'td[name="product_id"] input[role="combobox"]'
    )
    product_editor.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT)
    if product_editor.count() != 1:
        raise RuntimeError(
            'Ambiguous new Product editor on Odoo transfer. '
            'Manual Review required.'
        )
    row_id = _text(product_editor.locator('xpath=ancestor::tr[1]').get_attribute('data-id'))
    product_editor.fill(sku)
    _select_exact_stock_product_option(page, sku)

    # The selected new row has a numeric Demand editor (captured Nov 14 HTML).
    # Fill it before leaving edit mode, because Odoo may not save a new row
    # when the required quantity or unit remains empty.
    row = _operation_row_by_id(page, row_id)
    qty = row.locator('td[name="product_uom_qty"] input:not([type="hidden"])')
    if qty.count() != 1 or not qty.first.is_visible():
        qty = _operations_table(page).locator(
            'table.o_list_table tbody tr.o_selected_row '
            'td[name="product_uom_qty"] input:not([type="hidden"])'
        )
    if qty.count() != 1:
        raise RuntimeError(
            f'Odoo could not identify the new Demand editor for {sku}. '
            'The created TC/IN needs review, not another Return.'
        )
    qty.first.fill(str(quantity))
    _transfer_heading(page).click(timeout=DEFAULT_TIMEOUT)

    # The added row must be committed and readable by exact SKU before
    # another Add a Product click or Validate is allowed.
    _wait_for_operation_skus(page, {sku})
    found = [r for r in _read_operation_rows(page) if r['sku'] == sku]
    if len(found) != 1:
        raise RuntimeError(f'Odoo did not save the new product {sku}.')
    if found[0]['quantity'] != Decimal(quantity):
        _edit_operation_demand(page, sku, quantity)
    print(f'ODOO NO-DELIVERY PRODUCT ADDED: {sku} x {quantity}')


def _ensure_deliveryless_stock_moves(page, desired: dict[str, int]):
    """Only add absent SKUs. Never delete or duplicate saved stock moves."""
    current = _read_operation_rows(page, allow_empty=True)
    if any(not line['sku'] for line in current):
        raise RuntimeError(
            'Odoo transfer has a blank/partially entered Operations row. '
            'Review it before resuming; no duplicate row will be added.'
        )
    counts = {}
    for line in current:
        counts[line['sku']] = counts.get(line['sku'], 0) + 1
    if any(qty > 1 for qty in counts.values()):
        raise RuntimeError('Existing transfer contains duplicate SKU rows.')
    for sku, qty in desired.items():
        if sku not in counts:
            _add_missing_stock_move(page, sku, qty)
    _wait_for_operation_skus(page, desired)

def _set_quantities_on_draft_transfer(
    page, items: list[dict], *, manual_stock_entry=False,
    order_id='', platform='Shopee',
) -> dict:
    """Modify an existing unsubmitted TC/IN; never open a new Return.

    This method checks exact SKUs and demand quantities, not stock status.
    Recovery must skip all modifications when Grant Approval already exists.
    """
    desired = _requested_return_quantities(items)
    transfer = _capture_transfer(page)
    if manual_stock_entry:
        if not _text(order_id):
            raise RuntimeError(
                'No Sales Order ID is available for an empty-delivery '
                'transfer. Existing TC/IN must be reviewed manually.'
            )
        _ensure_deliveryless_transfer_header(page, order_id, platform)
        _ensure_deliveryless_stock_moves(page, desired)
    initial = _wait_for_operation_skus(page, desired)

    counts = {}
    for row in initial:
        if row["sku"]:
            counts[row["sku"]] = counts.get(row["sku"], 0) + 1
        elif row["quantity"] != 0:
            raise RuntimeError(
                "Unrecognized product with nonzero Demand in Odoo Operations. "
                "Manual review required."
            )
    duplicates = sorted(sku for sku, count in counts.items() if count > 1)
    if duplicates:
        raise RuntimeError(
            "Duplicate SKU rows in Odoo transfer need manual handling: "
            + ", ".join(duplicates)
        )

    # Never return unrelated products simply because they share the Sales Order.
    for row in initial:
        if row["sku"] not in desired and row["quantity"] != 0:
            _edit_operation_demand(page, row["sku"], 0)

    for sku, quantity in desired.items():
        current = [
            row for row in _read_operation_rows(page) if row["sku"] == sku
        ]
        if len(current) != 1:
            raise RuntimeError(
                f"Draft transfer cannot safely locate SKU {sku}; "
                "manual review required."
            )
        if current[0]["quantity"] != Decimal(quantity):
            _edit_operation_demand(page, sku, quantity)

    _save_operation_demands(page)
    _verify_operation_demands(page, desired)
    return {
        "transfer_id": transfer["transfer_id"],
        "transfer_url": transfer["transfer_url"],
        "demand_verified": True,
    }


def _open_return_transfer(
    page,
    order_id: str,
    items: list[dict],
    before_create=None,
    on_transfer_created=None,
    platform='Shopee',
):
    """Odoo Nov 2026: wizard creates a draft, THEN Operations Demand is edited.

    The v1.0.2-test checkpoint callback is still executed BEFORE the
    irreversible Return action. on_transfer_created additionally persists
    the TC/IN identity before any Demand editing, keeping retry disabled.
    """
    _requested_return_quantities(items)

    # The Helpdesk Return button is sometimes moved into Odoo's responsive
    # More menu. Do not assume every modal has an exposed ARIA dialog role.
    dialog = _open_helpdesk_return_dialog(page)

    sales = dialog.locator(
        'div[name="sale_order_id"] input.o-autocomplete--input'
    ).first
    sales.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    wanted_order = _text(order_id)
    if _text(sales.input_value()) != wanted_order:
        # A matching Odoo Sales Order suggestion is the required evidence.
        # Do not proceed on a typed value alone or a "No Record" result.
        sales.fill(wanted_order[-4:])
        choice = page.get_by_role("option", name=wanted_order, exact=True)
        try:
            choice.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
            choice.click(timeout=DEFAULT_TIMEOUT)
        except Exception as error:
            raise OdooReturnNotReadyError(
                f"Sales Order {wanted_order} could not be selected from "
                "Odoo's suggestions (it may show 'No Record'). "
                "No stock Return was created."
            ) from error

    deadline = time.monotonic() + DEFAULT_TIMEOUT / 1000
    while _text(sales.input_value()) != wanted_order and time.monotonic() < deadline:
        page.wait_for_timeout(200)
    if _text(sales.input_value()) != wanted_order:
        raise OdooReturnNotReadyError(
            f"Odoo selected the wrong Sales Order. Expected {wanted_order}."
        )

    # Nov 14: Odoo's wizard may leave Delivery to Return empty despite an
    # exact, selectable Sales Order suggestion. Delivery is OPTIONAL here;
    # Odoo's own action_return_picking decides whether the Return is allowed.
    # Capture any populated value for audit/recovery, but never wait for it.
    delivery_id = ""
    delivery = dialog.locator(
        'div[name="picking_id"] input.o-autocomplete--input'
    ).first
    if delivery.count():
        try:
            delivery_id = _text(delivery.input_value(timeout=2000))
        except Exception:
            # The dependent field may be re-rendering; it is not a gate.
            pass
    print(
        f"ODOO RETURN WIZARD: Sales Order={wanted_order}, "
        f"Delivery={delivery_id or '(not selected; optional)'}"
    )

    create = dialog.locator('button[name="action_return_picking"]')
    create.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    if not create.is_enabled():
        raise OdooReturnNotReadyError(
            "Odoo Return button is disabled; no TC/IN was created."
        )

    # Irreversible boundary: the next click may create a TC/IN even when
    # Playwright loses connection before receiving confirmation.
    if before_create:
        before_create()
    create.click()

    # A stock.picking DRAFT now exists. If any later action fails, do NOT
    # create another Return; the main app's manual-review checkpoint blocks it.
    transfer = _capture_transfer(page)
    if on_transfer_created:
        on_transfer_created({
            "transfer_id": transfer["transfer_id"],
            "transfer_url": transfer["transfer_url"],
            "delivery_to_return": delivery_id,
            "manual_stock_entry_required": not bool(delivery_id),
        })
    print(
        "ODOO DRAFT CREATED:", transfer["transfer_id"],
        "- setting Operations Demand without creating another Return"
    )
    return _set_quantities_on_draft_transfer(
        page, items, manual_stock_entry=not bool(delivery_id),
        order_id=order_id, platform=platform,
    )



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


def _odoo_danger_notification(page) -> str:
    """Only explicitly marked danger notifications count as stock errors.

    Generic ARIA alerts can be harmless approval/status messages in Odoo.
    """
    notices = page.locator(
        '.o_notification_manager .o_notification-danger, '
        '.o_notification_manager .alert-danger'
    )
    for i in range(notices.count()):
        notice = notices.nth(i)
        if notice.is_visible():
            return _text(notice.inner_text(timeout=1500)) or 'Odoo danger notification'
    return ''


def _visible_zero_demand_warning(page):
    """Return the exact active Odoo Zero Demand Warning dialog, if present.

    The name and title are checked together to avoid selecting an unrelated
    modal or a similarly named action in the stock picking.
    """
    title = page.locator('h4.modal-title').filter(
        has_text=re.compile(r'^\s*Zero Demand Warning\s*$', re.I)
    )
    for selector in ('div[role="dialog"]:visible', '.modal-content:visible'):
        candidates = page.locator(selector).filter(has=title)
        if candidates.count():
            if candidates.count() != 1:
                raise RuntimeError(
                    'Multiple Odoo Zero Demand Warning dialogs are present. '
                    'Manual Review required; do not choose an action blindly.'
                )
            return candidates.first
    return None


def _transfer_id_behind_warning(page) -> str:
    """Read the stock transfer identity without an accessibility-role wait.

    When Odoo opens a modal, its background can be aria-hidden/inert. A
    get_by_role('heading') wait against that background can appear to hang
    while Keep lines is plainly visible. Raw DOM text is still accessible.
    Both available identity locations must agree when both are rendered.
    """
    candidates = page.locator(
        '.oe_title div[name="name"] span, '
        '.oe_title h1, '
        '.o_control_panel_breadcrumbs .o_last_breadcrumb_item'
    ).all_text_contents()
    found = {_TRANSFER_ID_RE.search(_text(value)).group(0)
             for value in candidates if _TRANSFER_ID_RE.search(_text(value))}
    if len(found) != 1:
        raise RuntimeError(
            'Cannot positively identify the stock transfer behind the Zero '
            'Demand Warning. Manual Review required; Keep lines not clicked.'
        )
    return next(iter(found))


def _keep_verified_zero_demand_lines(page, expected_by_sku: dict[str, int],
                                     transfer_id: str) -> bool:
    """Handle only the Odoo Zero Demand Warning after a Validate action.

    For an exact, already-created TC/IN, verify the target SKU quantities and
    every non-target row's zero Demand BEFORE clicking Odoo's Keep lines.
    Clicking Keep lines is a continuation of the prior Validate, NOT a second
    Validate. On any uncertain click or unexpected dialog, fail closed.
    """
    dialog = _visible_zero_demand_warning(page)
    if dialog is None:
        return False

    if ZERO_DEMAND_WARNING_ACTION != 'keep_lines':
        raise RuntimeError(
            f'Unsupported Zero Demand policy: {ZERO_DEMAND_WARNING_ACTION!r}. '
            'Manual Review required.'
        )
    if not expected_by_sku or any(int(qty) <= 0 for qty in expected_by_sku.values()):
        raise RuntimeError(
            'Zero Demand Warning opened without a positive, verified target '
            'SKU/QTY mapping. Manual Review required.'
        )

    actual = _transfer_id_behind_warning(page)
    if actual != transfer_id:
        raise RuntimeError(
            f'Zero Demand Warning is on transfer {actual}, expected '
            f'{transfer_id}. No action taken.'
        )
    _verify_operation_demands(
        page, expected_by_sku, warning_dialog_open=True
    )
    rows = _read_operation_rows(page, warning_dialog_open=True)
    zero_rows = [row for row in rows if row['sku'] not in expected_by_sku
                 and row['quantity'] == 0]
    if not zero_rows:
        raise RuntimeError(
            f'Odoo showed Zero Demand Warning on {transfer_id}, but there '
            'is no verified unrelated zero-demand row. Review manually.'
        )

    keep = dialog.locator('button[name="process"][type="object"]')
    if keep.count() != 1 or _text(keep.first.inner_text()).casefold() != 'keep lines':
        raise RuntimeError(
            'The exact Odoo Keep lines button was not found. '
            'Do not click Remove lines or Validate again.'
        )
    print('ODOO ZERO DEMAND WARNING: verified ' + transfer_id + ' | target ' +
          ', '.join(f'{sku}={qty}' for sku, qty in expected_by_sku.items()) +
          ' | preserving zero-demand SKU(s): ' +
          ', '.join((row['sku'] or 'unidentified') for row in zero_rows))
    # Capture the ACTUAL modal DOM node. A locator is live and can retarget a
    # newly opened second warning; waiting for that locator to be hidden then
    # appears to hang even though the first Keep lines click succeeded.
    original_dialog_node = dialog.element_handle(timeout=2_000)
    if original_dialog_node is None:
        raise RuntimeError('Zero Demand Warning disappeared before Keep lines. '
                           'Do not click Validate; review the existing transfer.')
    # Do not retry if the browser action times out: Odoo may have accepted it.
    try:
        keep.click(timeout=5_000, no_wait_after=True)
        original_dialog_node.wait_for_element_state('hidden', timeout=7_000)
    except Exception as error:
        raise RuntimeError(
            'Keep lines was attempted on an existing Odoo transfer, but the '
            'dialog did not conclusively close. Keep Manual Review; do not '
            'press Keep lines or Validate again automatically.'
        ) from error
    problem = _odoo_danger_notification(page)
    if problem:
        raise RuntimeError(
            f'Odoo reported an error after Keep lines on {transfer_id}: '
            f'{problem}. Manual Review required; do not Validate again.'
        )
    print(f'ODOO ZERO DEMAND WARNING: Keep lines confirmed for {transfer_id}')
    return True


def _settle_zero_demand_warnings(page, expected_by_sku: dict[str, int],
                                 transfer_id: str,
                                 *, timeout_ms: int = 1_500,
                                 on_keep_lines=None) -> int:
    """Handle successive post-action Zero Demand Warning dialogs safely.

    Only the exact `Keep lines` action is used, and only after verified
    product/Demand/transfer identity. No Validate or Remove lines clicks.
    We also allow Odoo a brief moment to display a delayed warning after a
    QC confirmation; a burst of repeated warnings fails closed.
    """
    handled = 0
    deadline = time.monotonic() + timeout_ms / 1000
    quiet_since = None
    while time.monotonic() < deadline:
        if _keep_verified_zero_demand_lines(page, expected_by_sku, transfer_id):
            handled += 1
            # The callback persists post-warning evidence before any later
            # Validate can be attempted, including on an interrupted run.
            if on_keep_lines:
                on_keep_lines()
            quiet_since = None
            if handled > 8:
                raise RuntimeError(
                    f'Odoo opened excessive Zero Demand Warning dialogs on '
                    f'{transfer_id}. Manual Review required; no Validate retry.'
                )
            continue
        if quiet_since is None:
            quiet_since = time.monotonic()
        if time.monotonic() - quiet_since >= 0.5:
            break
        page.wait_for_timeout(100)
    return handled


def _warehouse_handoff_activity(page) -> dict | None:
    """Return an independently verifiable warehouse activity on this TC/IN.

    "Grant Approval" is recognized exactly as shown by Odoo (Nov 2026).
    A pending "To Do" is accepted ONLY when its title/assignee identifies
    warehouse staff or a name in WAREHOUSE_PERSONNEL_NAMES. The existence of
    a Validate button, its Studio approval avatar, "Mark as To Do", or an
    unrelated activity alone does NOT establish a warehouse handoff.

    Returns an activity description with type=grant_approval or warehouse_todo.
    This function does not read Draft/Ready/Done stock status.
    """
    activities = page.locator('.o-mail-ActivityList .o-mail-Activity')
    approved_names = {
        _text(name).casefold() for name in WAREHOUSE_PERSONNEL_NAMES
        if _text(name)
    }
    for index in range(activities.count()):
        activity = activities.nth(index)
        if not activity.is_visible():
            continue
        # Pending planned activities have Mark Done. Historical chatter notes
        # (and completed activities) must never satisfy the handoff check.
        pending = activity.locator('.o-mail-Activity-markDone')
        if not pending.count() or not pending.first.is_visible():
            continue

        info = activity.locator('.o-mail-Activity-info').first
        if not info.count():
            continue
        label_nodes = info.locator('.fw-bolder')
        label_parts = [
            _text(t).strip('“”\" ') for t in label_nodes.all_inner_texts()
        ]
        # Expected: "Today:", "Grant Approval", "for Name".
        title = _text(label_parts[1]) if len(label_parts) > 1 else ''
        if not title:
            # Layout-compatible fallback, but never accept the text of the
            # entire chatter (which might include unrelated approvals).
            info_text = _text(info.inner_text())
            quoted = re.search(r'[“\"]([^”\"]+)[”\"]', info_text)
            title = _text(quoted.group(1)) if quoted else ''
        assignee_nodes = info.locator('.o-mail-Activity-user')
        assignee = ' '.join(assignee_nodes.all_inner_texts()).strip()
        assignee = re.sub(r'^\s*for\s+', '', assignee, flags=re.I).strip()
        if not title:
            continue

        # The observed warehouse approval task already has dedicated naming.
        if re.search(r'\bGrant\s+Approval\b', title, re.I):
            return {'kind': 'grant_approval', 'title': title, 'assignee': assignee}

        # Alternate warehouse To Do labels must have evidence they belong
        # specifically to the warehouse, not to unrelated planned activities.
        title_is_todo = bool(re.search(
            r'\bTo[ -]?Do\b|\bWarehouse\s+Confirmation\b', title, re.I
        ))
        title_is_approval = bool(re.search(r'\bApproval\b', title, re.I))
        warehouse_named = bool(re.search(
            r'\bWarehouse\b|\bStock\s*(?:Room|Team|Department)\b|'
            r'\bInventory\s*(?:Team|Department)\b|\bReceiving\s*(?:Team|Department)\b',
            f'{title} {assignee}', re.I
        ))
        named_staff = bool(assignee and assignee.casefold() in approved_names)
        if (title_is_todo or title_is_approval) and (warehouse_named or named_staff):
            return {'kind': 'warehouse_todo', 'title': title, 'assignee': assignee}
    return None


def _warehouse_grant_approval_visible(page) -> bool:
    """Backward-compatible Boolean for warehouse approval OR verified To Do."""
    return _warehouse_handoff_activity(page) is not None


def _wait_for_new_stock_handoff(page, transfer_id: str,
                                timeout_ms: int = 25_000,
                                expected_by_sku: dict[str, int] | None = None,
                                *, allow_missing: bool = False,
                                on_keep_lines=None) -> str | None:
    """Verify actual warehouse Grant Approval or assigned warehouse To Do.

    Never confuse the static Studio "Waiting for approval" button icon with
    a created warehouse activity. Do not check Odoo stock status.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        # Odoo may ask whether to preserve unrelated zero-demand lines.
        # This is a post-Validate continuation, not a stock-state check.
        kept_lines = _keep_verified_zero_demand_lines(
            page, expected_by_sku or {}, transfer_id
        )
        if kept_lines and on_keep_lines:
            on_keep_lines()
        activity = _warehouse_handoff_activity(page)
        if activity:
            if not _pending_validation_safe_to_leave(page):
                raise RuntimeError(
                    f'Odoo transfer {transfer_id} has a warehouse activity '
                    'but a blocking dialog/error is still open. Review manually.'
                )
            print(f'ODOO WAREHOUSE HANDOFF CONFIRMED: {transfer_id} | '
                  f'{activity["title"]} | {activity["assignee"] or "no assignee shown"}. '
                  'Request recorded; stock posting is not confirmed.')
            return activity['kind']
        problem = _odoo_danger_notification(page)
        if problem:
            raise RuntimeError(
                f'Odoo reported an error on {transfer_id} after Validate: '
                f'{problem}. Existing transfer requires review; do NOT Validate again.'
            )
        page.wait_for_timeout(250)
    if allow_missing:
        return None
    raise RuntimeError(
        f'Odoo transfer {transfer_id} shows neither a pending Grant Approval '
        'nor a verified warehouse To Do after Validate. Keep Manual Review; '
        'do not press Validate a second time.'
    )


def _wait_for_existing_handoff(page, timeout_ms=6_000) -> bool:
    """Wait for transfer-local warehouse activity hydration on recovery.

    This can acknowledge a prior Validate without issuing it again.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _warehouse_handoff_activity(page):
            return True
        page.wait_for_timeout(250)
    return False


def _group_handoff_complete(result: dict) -> bool:
    """Only a real New warehouse handoff or completed QC allows progression."""
    if result.get('validated') is True:  # Legacy completed checkpoints.
        return True
    if (result.get('classification') in {'Unsealed', 'Defective'}
            and result.get('qc_completed') is True):
        return True
    return bool(
        result.get('classification') == 'New'
        and result.get('destination_location') in NEW_STOCK_DESTINATIONS
        and result.get('warehouse_handoff_complete') is True
        and (result.get('warehouse_approval_requested') is True
             or result.get('warehouse_todo_created') is True)
    )


def _pending_group_validation(results: list[dict]) -> list[dict]:
    """Returns which still block next/retry/completion because of QC or stock."""
    return [result for result in results if not _group_handoff_complete(result)]


def _warehouse_approval_pending_ids(results: list[dict]) -> list[str]:
    """Keep legacy checkpoint key while tracking either warehouse task kind."""
    return [result['transfer_id'] for result in results
            if (result.get('warehouse_approval_requested') is True
                or result.get('warehouse_todo_created') is True)
            and not result.get('validated')]


def _pending_validation_safe_to_leave(page) -> bool:
    """No blocking dialog or explicit Odoo danger notice is present.

    Does not inspect the stock picking's Draft / Ready / Done status.
    This is only a UI-safety check; handoff still needs positive evidence.
    """
    if page.locator('.modal-content:visible, [role="dialog"]:visible').count():
        return False
    return not bool(_odoo_danger_notification(page))


def _click_validate(page, *, expected_by_sku=None, transfer_id='',
                    on_keep_lines=None):
    """Invoke ONE Validate action across current, legacy and compact UIs.

    Current Odoo (Nov 11):
        button[name="button_validate"].o_btn_validate[type="object"]
        The child Studio approval avatar is NOT an HTML disabled attribute.
    Earlier Odoo: accessible "Validate" button / name="button_validate".
    Compact Odoo: same action inside the statusbar More dropdown.

    IMPORTANT: Never preemptively reject an action because a single
    is_enabled() snapshot was false. Playwright's click performs an actionable
    wait. If click fails/times out, inspect the page for the *specific* Zero
    Demand Warning before declaring the outcome unknown. In Odoo, a successful
    Validate can open that warning while Playwright is still waiting for the
    original click, causing the new modal to intercept its pointer events.
    The exact TC/IN and every Demand must match before clicking Keep lines.
    Never try an alternate Validate if the click outcome is uncertain.
    For New stock, a *separate caller* may authorize exactly one later
    Validate only after a verified Keep lines continuation and a durable
    second-click checkpoint. This helper never retries its own click.
    """
    expected_by_sku = expected_by_sku or {}
    transfer_id = _text(transfer_id)

    def continue_existing_zero_demand_warning() -> bool:
        # A visible warning is evidence the Validate action already started.
        # Handle it without issuing a second Validate, even when it existed
        # before the current function was entered (e.g., a resumed UI session).
        if _visible_zero_demand_warning(page) is None:
            return False
        if not expected_by_sku or not _TRANSFER_ID_RE.fullmatch(transfer_id):
            raise RuntimeError(
                'Odoo Zero Demand Warning is open, but the current return has '
                'no verified transfer ID/SKU quantities. Manual Review required; '
                'do not Validate again or select a warning action blindly.'
            )
        handled = _keep_verified_zero_demand_lines(
            page, expected_by_sku, transfer_id
        )
        if handled:
            if on_keep_lines:
                on_keep_lines()
            print(
                'ODOO VALIDATE: Zero Demand Warning handled using Keep lines '
                f'for {transfer_id}; the caller will verify the next handoff.'
            )
        return handled

    # Check before attempting Mark as To Do or Validate: either action is
    # unsafe while an earlier Validate's confirmation dialog is still open.
    if continue_existing_zero_demand_warning():
        return

    statusbar = page.locator('.o_form_statusbar').first
    statusbar.wait_for(state='visible', timeout=SLOW_ODOO_TIMEOUT)

    # Preserve the old workflow: on a freshly Draft picking, Odoo exposes
    # "Mark as To Do" before the normal Validate action.
    confirm = statusbar.locator('button[name="action_confirm"]:visible').first
    if confirm.count() and confirm.is_enabled():
        confirm.click(timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(ODOO_COMMIT_BUFFER_MS)

    def click_once(action, selector_description):
        # No fallthrough after a click attempt. Navigation, validation or
        # approval submission may succeed even if browser feedback times out.
        print(f'ODOO VALIDATE: attempting {selector_description} exactly once')
        try:
            # Odoo may open Zero Demand Warning between the mouse-down and
            # mouse-up stages. Playwright then retries the original Validate
            # against a modal overlay. Bound that retry to four seconds and
            # immediately inspect the confirmation instead of looking hung.
            # No alternative Validate selector is tried after this boundary.
            action.click(timeout=4_000, no_wait_after=True)
        except Exception as error:
            # Clicking Validate *can* succeed and open Zero Demand Warning,
            # while Playwright reports that the modal intercepted a retry of
            # the original click. This is not grounds for another Validate.
            # Exact TC/IN and Demand verification is performed inside the
            # continuation helper before any click on Keep lines.
            if continue_existing_zero_demand_warning():
                print(
                    'ODOO VALIDATE: original click returned '
                    f'{type(error).__name__}, but the expected Zero Demand '
                    'Warning was verified and completed. No second Validate.'
                )
                return
            evidence = _warehouse_handoff_activity(page)
            if evidence:
                print('ODOO VALIDATE: click raised but warehouse handoff is visible; '
                      'not clicking again.')
                return
            raise RuntimeError(
                f'Odoo Validate action outcome is uncertain at {page.url}: '
                f'{selector_description}; {type(error).__name__}: {error}. '
                'The transfer already exists. Keep Manual Review; DO NOT '
                'click Validate a second time automatically.'
            ) from error
        else:
            # A click may return *successfully* even though Odoo immediately
            # opened Zero Demand Warning. Resolve it before waiting for the
            # warehouse handoff. Keep errors must not be reclassified as a
            # Validate click failure or swallowed by a broad except clause.
            if continue_existing_zero_demand_warning():
                print('ODOO VALIDATE: prompt resolved immediately after click; '
                      'no new Validate was sent.')

    # First use the exact current Odoo button, retaining previous locator
    # styles as fallback. .is_visible is only used for placement, not enabled.
    direct_selectors = (
        'button[name="button_validate"][type="object"].o_btn_validate:visible',
        'button[name="button_validate"]:visible',
        'button.o_btn_validate:visible',
    )
    for selector in direct_selectors:
        candidate = statusbar.locator(selector).first
        if candidate.count():
            click_once(candidate, selector)
            return

    # Older accessible-name layout without stable name attributes.
    legacy = statusbar.get_by_role(
        'button', name=re.compile(r'^\s*Validate\b', re.I)
    ).first
    if legacy.count() and legacy.is_visible():
        click_once(legacy, 'legacy accessible Validate button')
        return

    # Odoo's responsive statusbar can collapse actions into a More dropdown.
    more = statusbar.locator(
        '.o_statusbar_buttons button[title="More"]:visible, '
        '.o_statusbar_buttons button.o-dropdown.dropdown-toggle:visible'
    ).first
    if not more.count():
        raise RuntimeError(
            'Odoo Validate button was not found in either current or old '
            'layout; the return already exists. Manual Review required.'
        )
    more.click(timeout=DEFAULT_TIMEOUT)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        menus = page.locator(
            '.o-dropdown--menu:visible, .dropdown-menu:visible, '
            '[role="menu"]:visible'
        )
        candidates = menus.locator(
            'button[name="button_validate"], button.o_btn_validate'
        )
        if not candidates.count():
            candidates = menus.get_by_role(
                'button', name=re.compile(r'^\s*Validate\b', re.I)
            )
        if not candidates.count():
            candidates = menus.get_by_text('Validate', exact=True)
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            if candidate.is_visible():
                click_once(candidate, 'compact More > Validate')
                return
        page.wait_for_timeout(150)
    raise RuntimeError(
        'Odoo compact More menu has no visible Validate action. '
        'The transfer exists. Manual Review required; no duplicate Return.'
    )


def _existing_new_stock_destination_verified(page, destination='MNL/Stock'):
    """Confirm an existing picking has the saved, exact New-stock destination.

    Called on recovered transfers that have Grant Approval activities. It
    must not write to a warehouse-submitted transfer.
    """
    destination = _validated_new_stock_destination(destination)
    field = page.locator('div[name="location_dest_id"]').first
    field.wait_for(state='visible', timeout=DEFAULT_TIMEOUT)
    text_value = _text(field.inner_text(timeout=DEFAULT_TIMEOUT))
    inp = field.locator('input[role="combobox"]').first
    if inp.count():
        text_value += ' ' + _text(inp.input_value(timeout=DEFAULT_TIMEOUT))
    destination_pattern = rf'(?<![\w/]){re.escape(destination)}(?![\w/])'
    if not re.search(destination_pattern, text_value, re.I):
        raise RuntimeError(
            'Existing warehouse approval is visible but destination '
            f'{destination} cannot be positively verified. Review manually; '
            'no edit or second Validate will be attempted.'
        )


def _process_brand_new(page, before_validate=None, items=None,
                       destination='MNL/Stock', *, on_keep_lines=None,
                       before_second_validate=None,
                       resume_after_keep_lines=False):
    """Confirm the warehouse handoff without relying on Odoo stock status.

    Current Odoo may have a *two-step* Validate after an unrelated zero-demand
    row triggers Keep lines: Validate -> Keep lines -> Validate -> Grant Approval.
    The second Validate is allowed ONLY if Keep lines has been definitively
    confirmed and both the exact transfer and saved SKU/Demand remain correct.
    A durable checkpoint is mandatory BEFORE the second click. No third click
    is performed here, and an uncertain click is never silently retried.
    """
    destination = _validated_new_stock_destination(destination)
    transfer = _capture_transfer(page)
    transfer_id = transfer['transfer_id']
    requested = _requested_return_quantities(items or [])
    keep_lines_confirmed = bool(resume_after_keep_lines)

    def keep_lines_verified():
        nonlocal keep_lines_confirmed
        keep_lines_confirmed = True
        if on_keep_lines:
            on_keep_lines()

    _settle_zero_demand_warnings(
        page, requested, transfer_id, timeout_ms=700,
        on_keep_lines=keep_lines_verified,
    )
    activity = _warehouse_handoff_activity(page)
    if activity:
        _existing_new_stock_destination_verified(page, destination)
        if not _pending_validation_safe_to_leave(page):
            raise RuntimeError(
                f'Warehouse handoff on {transfer_id} exists but an Odoo '
                'dialog or danger notice requires review.'
            )
        print(f'ODOO EXISTING HANDOFF: {transfer_id}; '
              f'{activity["kind"]}, no Validate click needed.')
    else:
        if keep_lines_confirmed:
            # Prior Validate + Keep lines was positively observed (or durably
            # recorded before recovery). Do not issue the original Validate.
            _existing_new_stock_destination_verified(page, destination)
        else:
            destination_box = page.get_by_role(
                'combobox', name='Destination Location'
            )
            destination_box.wait_for(state='visible', timeout=SLOW_ODOO_TIMEOUT)
            destination_box.click()
            destination_box.fill(destination)
            page.get_by_role('option', name=destination, exact=True).click()
            transfer['heading'].click()
            page.wait_for_timeout(ODOO_COMMIT_BUFFER_MS)
            if before_validate:
                before_validate()  # Persist before the FIRST Validate.
            _click_validate(
                page, expected_by_sku=requested, transfer_id=transfer_id,
                on_keep_lines=keep_lines_verified,
            )

        # Give Odoo time to hydrate real planned activities. During this wait
        # it can also show a delayed Zero Demand Warning; the callback will
        # checkpoint Keep lines once the dialog has conclusively closed.
        _wait_for_new_stock_handoff(
            page, transfer_id, timeout_ms=5_000,
            expected_by_sku=requested, allow_missing=True,
            on_keep_lines=keep_lines_verified,
        )
        activity = _warehouse_handoff_activity(page)

        if not activity and not keep_lines_confirmed:
            # No confirmed Keep lines: never click Validate again. Preserve
            # the former wait for a slow first-Validate approval response.
            _wait_for_new_stock_handoff(
                page, transfer_id, timeout_ms=20_000,
                expected_by_sku=requested, allow_missing=True,
                on_keep_lines=keep_lines_verified,
            )
            activity = _warehouse_handoff_activity(page)

        if not activity and keep_lines_confirmed:
            # The first Validate was followed by the explicit Odoo warning.
            # A second click is an intentional, narrowly-scoped handoff step;
            # it must not be triggered by generic timeouts or stock status.
            if _visible_zero_demand_warning(page) is not None:
                raise RuntimeError(
                    f'{transfer_id} still has an unresolved Zero Demand Warning. '
                    'Do not click Validate; keep Manual Review.'
                )
            if not _pending_validation_safe_to_leave(page):
                raise RuntimeError(
                    f'{transfer_id} has a blocking dialog/Odoo error after '
                    'Keep lines. No second Validate was attempted.'
                )
            actual = _capture_transfer(page)['transfer_id']
            if actual != transfer_id:
                raise RuntimeError(
                    f'Expected {transfer_id}, but the current transfer is '
                    f'{actual}. No second Validate.'
                )
            _verify_operation_demands(page, requested)
            _existing_new_stock_destination_verified(page, destination)
            if _warehouse_handoff_activity(page):
                activity = _warehouse_handoff_activity(page)
            else:
                if before_second_validate is None:
                    raise RuntimeError(
                        f'{transfer_id} needs a second Validate after Keep '
                        'lines, but no durable second-click checkpoint is '
                        'available. Manual Review required.'
                    )
                # Callback persists an explicit at-most-once second attempt.
                # If process crashes or Playwright times out, Recovery must
                # not send a third click automatically.
                before_second_validate()
                print(f'ODOO NEW STOCK: verified Keep lines for {transfer_id}; '
                      'sending the single checkpointed second Validate.')
                _click_validate(
                    page, expected_by_sku=requested, transfer_id=transfer_id,
                    on_keep_lines=keep_lines_verified,
                )
                _wait_for_new_stock_handoff(
                    page, transfer_id, timeout_ms=25_000,
                    expected_by_sku=requested,
                    on_keep_lines=keep_lines_verified,
                )
                activity = _warehouse_handoff_activity(page)

        if not activity:
            raise RuntimeError(
                f'Odoo transfer {transfer_id} shows neither a pending Grant '
                'Approval nor a verified warehouse To Do. Keep Manual Review; '
                'no unverified Validate retry is allowed.'
            )
        if not _pending_validation_safe_to_leave(page):
            raise RuntimeError(
                f'{transfer_id} has a warehouse handoff but a blocking '
                'dialog/error is still open. Manual Review required.'
            )

    kind = activity['kind']
    return {
        'destination_location': destination,
        'qc_result': None,
        'transfer_id': transfer_id,
        'transfer_url': transfer['transfer_url'],
        'validated': False,  # Pending warehouse approval is NOT Done.
        'validation_pending': True,
        'warehouse_approval_requested': kind == 'grant_approval',
        'warehouse_todo_created': kind == 'warehouse_todo',
        'warehouse_handoff_signal': kind,
        'warehouse_handoff_activity_title': activity['title'],
        'warehouse_handoff_activity_assignee': activity['assignee'],
        'warehouse_handoff_complete': True,
        'stock_state': 'not_checked',
    }


def _wait_for_next_qc_dialog(
    page,
    expected_skus: set[str],
    processed_skus: set[str],
    expected_by_sku: dict[str, int] | None = None,
    transfer_id: str = '',
):
    """
    Wait for the next automatically opened TECHNICAL RETURN QC dialog and
    identify its SKU from the title.
    """
    elapsed = 0
    poll_ms = 250

    while elapsed < SLOW_ODOO_TIMEOUT:
        # When Odoo retains unrelated zero-demand lines, it can ask whether
        # to Keep lines before opening the normal TECHNICAL RETURN QC dialog.
        # Do not treat this warning as a failed Validate or try Validate again.
        if _keep_verified_zero_demand_lines(
            page, expected_by_sku or {}, transfer_id
        ):
            continue
        dialogs = page.locator('div[role="dialog"], .modal-content')
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
            if sku not in expected_skus:
                # "Keep lines" preserves zero-demand products. If Odoo
                # unexpectedly requests QC for one of those unrelated rows,
                # never apply the returned item's route to the wrong SKU.
                raise RuntimeError(
                    f'Odoo opened a QC dialog for unexpected SKU {sku} '
                    f'({title_text!r}). Expected: '
                    f'{", ".join(sorted(expected_skus))}. Manual Review '
                    'required; do not repeat Validate or auto-fail this item.'
                )
            if sku not in processed_skus:
                return dialog, sku, title_text

        # Validate can leave an unvalidated transfer without opening QC.
        # Only continue to another draft if no QC was applied and no modal,
        # error, or other pending on-screen interaction is present.
        if not processed_skus and elapsed >= 12_000 and \
                _pending_validation_safe_to_leave(page):
            return None, None, None
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
    before_validate=None,
    skip_validate=False,
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

    if not skip_validate:
        if before_validate:
            before_validate()
        _click_validate(
            page,
            expected_by_sku=_requested_return_quantities(items),
            transfer_id=transfer['transfer_id'],
        )

    while processed != expected:
        dialog, sku, title_text = _wait_for_next_qc_dialog(
            page,
            expected,
            processed,
            expected_by_sku=_requested_return_quantities(items),
            transfer_id=transfer['transfer_id'],
        )
        if dialog is None:
            # No QC was performed: validation is not complete (possibly an
            # approval hold). Never claim this transfer passed QC.
            return {
                "destination_location": None,
                "qc_result": None,
                "qc_results": [],
                "transfer_id": transfer["transfer_id"],
                "transfer_url": transfer["transfer_url"],
                "validated": False,
                "validation_pending": True,
                "stock_state": "not_checked",
            }
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
        # Confirmation must dismiss this SKU's QC dialog or move on to
        # another QC dialog. Do not rely on the stock status ribbon.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            same_qc = page.locator(
                'div[role="dialog"], .modal-content'
            ).filter(has_text=re.compile(
                rf'TECHNICAL\s+RETURN\s+QC.*\[{re.escape(sku)}\]', re.I | re.S
            ))
            if not any(same_qc.nth(j).is_visible()
                       for j in range(same_qc.count())):
                break
            issue = _odoo_danger_notification(page)
            if issue:
                raise RuntimeError(
                    f'QC Confirm for {sku} produced Odoo error: {issue}'
                )
            page.wait_for_timeout(200)
        else:
            raise RuntimeError(
                f'QC confirmation for {sku} did not close the dialog. '
                'Manual review required; do not repeat stock validation.'
            )

        processed.add(sku)
        qc_results.append({
            "sku": sku,
            "classification": item_by_sku[sku]["classification"],
            "qc_result": route,
        })

        # Small handoff buffer while Odoo closes this QC and opens the next.
        page.wait_for_timeout(350)
        _settle_zero_demand_warnings(
            page, _requested_return_quantities(items),
            transfer['transfer_id'], timeout_ms=1_200,
        )

    # All required SKU-specific QC dialogs were completed and dismissed.
    # A final warning must be cleared before leaving the existing transfer.
    _settle_zero_demand_warnings(
        page, _requested_return_quantities(items),
        transfer['transfer_id'], timeout_ms=1_000,
    )
    if not _pending_validation_safe_to_leave(page):
        raise RuntimeError(
            'Odoo still has a blocking dialog or danger notification after '
            'QC/Keep lines. Preserve existing TC/IN; Manual Review required.'
        )
    # We do NOT inspect stock Draft/Ready/Done and do NOT imply it is Done.
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
        "validated": False,
        "qc_completed": True,
        "validation_pending": False,
        "stock_state": "not_checked",
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


def _base_checkpoint(
    *,
    order_id: str,
    ticket_title: str,
    ticket_url: str,
    first_sku: str,
    tags: list[str],
    platform: str,
    new_stock_destination: str = 'MNL/Stock',
) -> dict:
    platform = _text(platform) or "Shopee"
    new_stock_destination = _validated_new_stock_destination(new_stock_destination)
    return {
        "order_id": _text(order_id),
        "ticket_title": ticket_title,
        "ticket_url": ticket_url,
        "product_sku": first_sku,
        "tags": list(tags),
        "platform": platform,
        "new_stock_destination": new_stock_destination,
        "customer": ODOO_CUSTOMER_BY_PLATFORM.get(
            platform,
            f"ECOMMERCE, {platform.upper()}",
        ),
        "returns": [],
        "next_return_index": 1,
        "resume_safe": bool(ticket_url),
        "setup_complete": False,
        "stage": "ticket_created" if ticket_url else "ticket_creation_in_progress",
    }


def _ensure_ticket_setup(page, checkpoint: dict, progress_callback=None,
                         checkpoint_callback=None):
    """Idempotently finish product, tags and priority on the SAME ticket."""
    if checkpoint.get("setup_complete"):
        return

    try:
        sku = checkpoint["product_sku"]
        _progress(progress_callback, f"Selecting existing Odoo product: {sku}")
        _select_product(page, sku)
        tags = checkpoint.get("tags") or []
        _progress(progress_callback, "Ensuring Odoo tag(s): " + ", ".join(tags))
        _select_tags(page, tags)
        _progress(progress_callback, "Setting priority to Urgent...")
        _set_urgent_priority(page)
    except Exception as error:
        checkpoint["stage"] = "ticket_setup_pending"
        checkpoint["resume_safe"] = True  # No stock return has been submitted.
        _checkpoint(checkpoint_callback, checkpoint, "odoo_ticket_setup_pending")
        raise OdooWorkflowPausedError(
            "The Odoo Helpdesk ticket was already created, but product/tag/"
            f"priority setup did not finish: {error}\n\n"
            f"Existing ticket: {checkpoint.get('ticket_url', '')}\n"
            "Use Retry Odoo Return & Continue after checking Odoo. "
            "The processor will reopen the SAME ticket, not create another.",
            checkpoint,
        ) from error

    checkpoint["setup_complete"] = True
    checkpoint["stage"] = "return_preparing"
    checkpoint["resume_safe"] = True
    _checkpoint(checkpoint_callback, checkpoint, "odoo_ticket_ready")


def _process_return_groups(
    page,
    order_id: str,
    returned_products: list[dict],
    checkpoint: dict,
    progress_callback=None,
    force_ticket_reload: bool = False,
    checkpoint_callback=None,
) -> dict:
    """
    Continue stock-return creation from a saved Helpdesk ticket.

    A checkpoint advances after a group reaches Done/QC, OR (for New only)
    once Odoo visibly creates the warehouse approval or To Do activity.
    A missing Sales Order/Delivery is retryable before the new wizard Return
    click. After that click, the new TC/IN must be inspected rather than
    automatically creating another transfer.
    """
    groups = _build_return_groups(returned_products)
    new_stock_destination = _validated_new_stock_destination(
        checkpoint.get('new_stock_destination', 'MNL/Stock')
    )
    return_results = list(checkpoint.get("returns") or [])
    next_index = int(
        checkpoint.get("next_return_index") or (len(return_results) + 1)
    )

    if next_index < 1:
        next_index = 1
    if next_index > len(groups) + 1:
        raise RuntimeError("Invalid Odoo restore-point return index.")

    for index in range(next_index, len(groups) + 1):
        group = groups[index - 1]

        if force_ticket_reload or index > 1:
            _progress(
                progress_callback,
                f"Opening saved Helpdesk ticket for Return #{index}...",
            )
            page.goto(
                checkpoint["ticket_url"],
                wait_until="domcontentloaded",
                timeout=SLOW_ODOO_TIMEOUT,
            )
            # Responsive Odoo moves Return into the statusbar More menu.
            # Waiting for the direct Return button can fail on compact screens.
            # The helper below will locate and click the proper action.
            page.locator(".o_form_statusbar").wait_for(
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

        pending_return = {
            # This release durably checkpoints BEFORE clicking Validate.
            # Older snapshots lack this guarantee and must not revalidate
            # uncertain transfer outcomes automatically.
            "validation_boundary_version": 2,
            "return_index": index,
            "decision": group["decision"],
            "classification": group["classification"],
            "status": group["status"],
            "items": [
                {"sku": _text(item["sku"]), "quantity": int(item["quantity"])}
                for item in group["items"]
            ],
        }

        def before_create_return():
            checkpoint["returns"] = return_results
            checkpoint["next_return_index"] = index
            checkpoint["pending_return"] = pending_return
            checkpoint["stage"] = "return_creation_in_flight"
            checkpoint["resume_safe"] = False
            _checkpoint(checkpoint_callback, checkpoint, "manual_review")

        def transfer_created(transfer):
            # A TC/IN now exists; record its identity immediately before
            # editing Demand, so a crash cannot trigger duplicate creation.
            pending_return.update({
                "transfer_id": transfer["transfer_id"],
                "transfer_url": transfer["transfer_url"],
                "delivery_to_return": transfer["delivery_to_return"],
                "manual_stock_entry_required": bool(
                    transfer.get("manual_stock_entry_required")
                ),
            })
            checkpoint["pending_return"] = pending_return
            checkpoint["stage"] = "return_draft_created"
            checkpoint["resume_safe"] = False
            _checkpoint(checkpoint_callback, checkpoint, "manual_review")

        try:
            _open_return_transfer(
                page, order_id, group["items"],
                before_create=before_create_return,
                on_transfer_created=transfer_created,
                platform=checkpoint.get('platform', 'Shopee'),
            )
            # Demand has been saved/verified on the created TC/IN, but the
            # transfer has NOT yet passed stock Validate and QC.
            checkpoint["stage"] = "return_demand_verified"
            checkpoint["resume_safe"] = False
            _checkpoint(checkpoint_callback, checkpoint, "manual_review")
        except OdooReturnNotReadyError as error:
            checkpoint["returns"] = return_results
            checkpoint["next_return_index"] = index
            checkpoint["pending_return"] = pending_return
            earlier_unvalidated = bool(_pending_group_validation(return_results))
            checkpoint["stage"] = (
                "inventory_pending_after_validation_hold" if earlier_unvalidated
                else "inventory_pending"
            )
            checkpoint["resume_safe"] = not earlier_unvalidated
            _checkpoint(
                checkpoint_callback, checkpoint,
                "manual_review" if earlier_unvalidated else "odoo_return_pending",
            )
            raise OdooWorkflowPausedError(
                (
                    f"{error}\n\n"
                    f"Odoo Helpdesk ticket already saved: "
                    f"{checkpoint['ticket_title']}\n"
                    "Check the Sales Order suggestion and Odoo's Return/More "
                    "action. Delivery to Return may be blank. "
                    "Once ready, click Retry Odoo Return & Continue. The "
                    "existing Helpdesk ticket will be reused."
                ),
                checkpoint,
            ) from error
        except OdooReturnOpenUncertainError as error:
            # Do not auto-retry when the Helpdesk action navigated somewhere
            # unexpected or Odoo showed another dialog/notification.
            checkpoint["returns"] = return_results
            checkpoint["next_return_index"] = index
            checkpoint["pending_return"] = pending_return
            checkpoint["stage"] = "return_wizard_uncertain"
            checkpoint["resume_safe"] = False
            _checkpoint(checkpoint_callback, checkpoint, "manual_review")
            raise OdooWorkflowPausedError(
                f"Odoo Return action outcome is uncertain: {error}\n\n"
                "Inspect this ticket and its Transfers/Returns before trying "
                "any new stock return. No automatic retry is permitted.",
                checkpoint,
            ) from error

        def before_validate():
            pending_return['validation_action_in_flight'] = True
            checkpoint['pending_return'] = pending_return
            checkpoint['stage'] = 'return_validation_action_in_flight'
            checkpoint['resume_safe'] = False
            _checkpoint(checkpoint_callback, checkpoint, 'manual_review')

        def on_keep_lines():
            pending_return['validation_action_in_flight'] = True
            pending_return['zero_demand_keep_lines_confirmed'] = True
            checkpoint['pending_return'] = pending_return
            if not pending_return.get('post_keep_lines_second_validate_in_flight'):
                checkpoint['stage'] = 'return_zero_demand_keep_lines_confirmed'
            checkpoint['resume_safe'] = False
            _checkpoint(checkpoint_callback, checkpoint, 'manual_review')

        def before_second_validate():
            if not pending_return.get('zero_demand_keep_lines_confirmed'):
                raise RuntimeError('Missing verified Keep lines checkpoint.')
            if pending_return.get('post_keep_lines_second_validate_in_flight'):
                raise RuntimeError('Second Validate already attempted. Manual Review.')
            pending_return['post_keep_lines_second_validate_in_flight'] = True
            checkpoint['pending_return'] = pending_return
            checkpoint['stage'] = 'return_post_keep_lines_second_validate_in_flight'
            checkpoint['resume_safe'] = False
            _checkpoint(checkpoint_callback, checkpoint, 'manual_review')

        if group["classification"] == "New":
            stock_result = _process_brand_new(
                page, before_validate=before_validate, items=group['items'],
                destination=new_stock_destination,
                on_keep_lines=on_keep_lines,
                before_second_validate=before_second_validate,
            )
        else:
            stock_result = _process_open_box_or_defective(
                page, group["items"], before_validate=before_validate,
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
        checkpoint["returns"] = return_results
        checkpoint["next_return_index"] = index + 1
        checkpoint.pop("pending_return", None)
        unresolved = _pending_group_validation(return_results)
        checkpoint['pending_warehouse_approval_transfer_ids'] = (
            _warehouse_approval_pending_ids(return_results)
        )
        if unresolved:
            checkpoint["stage"] = "return_created_waiting_validation"
            checkpoint["resume_safe"] = False
            checkpoint["pending_validation_transfer_ids"] = [
                r["transfer_id"] for r in unresolved
            ]
            # The TC/IN identity is durable BEFORE navigating to the ticket.
            _checkpoint(checkpoint_callback, checkpoint, "manual_review")
        else:
            checkpoint.pop('pending_validation_transfer_ids', None)
            checkpoint["stage"] = (
                'warehouse_handoff_requested'
                if checkpoint['pending_warehouse_approval_transfer_ids']
                else "return_group_completed"
            )
            checkpoint["resume_safe"] = True
            # Durable TC/IN record BEFORE starting the next return group.
            _checkpoint(checkpoint_callback, checkpoint, "odoo_ticket_ready")

        if stock_result.get('qc_completed'):
            result_message = f'Return #{index} QC completed: '
        elif _group_handoff_complete(return_results[-1]):
            result_message = f'Return #{index} sent for warehouse approval: '
        else:
            result_message = f'Return #{index} pending Odoo validation/QC: '
        _progress(progress_callback, result_message + stock_result['transfer_id'])

    pending_validation = _pending_group_validation(return_results)
    if pending_validation:
        # All intended independent drafts have now been created, but one or
        # more failed QC or lack a confirmed warehouse handoff. Block Lark.
        checkpoint["returns"] = return_results
        checkpoint["next_return_index"] = len(groups) + 1
        checkpoint["resume_safe"] = False
        checkpoint["stage"] = "returns_awaiting_validation"
        checkpoint["pending_validation_transfer_ids"] = [
            r["transfer_id"] for r in pending_validation
        ]
        _checkpoint(checkpoint_callback, checkpoint, "manual_review")
        raise OdooWorkflowPausedError(
            "All requested Odoo Return drafts were created, but some "
            "transfers lack a confirmed warehouse handoff or completed "
            "required QC. Review these in Odoo. "
            "Lark was NOT filed, and duplicate creation is BLOCKED.\n\n"
            "Pending transfer(s): "
            + ", ".join(checkpoint["pending_validation_transfer_ids"])
            + "\nHelpdesk ticket: " + checkpoint["ticket_url"],
            checkpoint,
        )

    checkpoint["returns"] = return_results
    checkpoint["next_return_index"] = None
    checkpoint["resume_safe"] = False
    checkpoint.pop("pending_return", None)
    checkpoint.pop('pending_validation_transfer_ids', None)
    checkpoint['pending_warehouse_approval_transfer_ids'] = (
        _warehouse_approval_pending_ids(return_results)
    )
    checkpoint["stage"] = "returns_complete"
    # An outstanding warehouse approval is explicitly recorded but is NOT a
    # blocker for Lark under the agreed New -> MNL/Stock handoff policy.
    # Do not change the truthful per-transfer validated=False field.
    # Make these results durable before any Lark filing starts.
    _checkpoint(checkpoint_callback, checkpoint, "odoo_returns_complete")
    return checkpoint


def resume_odoo_returns(
    context,
    order_id: str,
    returned_products: list[dict],
    checkpoint: dict,
    progress_callback=None,
    checkpoint_callback=None,
) -> dict:
    """Resume only the pending Odoo stock return(s) on an existing ticket."""
    if not checkpoint:
        raise ValueError("No Odoo restore point is available.")
    if not checkpoint.get("resume_safe", False):
        raise RuntimeError(
            "This Odoo restore point is not marked safe to retry automatically."
        )
    if _text(checkpoint.get("order_id")) != _text(order_id):
        raise RuntimeError(
            "Odoo restore point does not belong to the currently loaded order."
        )
    if not _TICKET_URL_RE.fullmatch(_text(checkpoint.get("ticket_url"))):
        raise RuntimeError(
            "Restore point has no verified Odoo ticket URL. Automatic retry "
            "is blocked; inspect the ticket manually."
        )

    page = get_or_open_odoo_page(context)
    page.bring_to_front()
    _progress(
        progress_callback,
        "Resuming Odoo from saved Helpdesk ticket; no new ticket will be created...",
    )
    if not checkpoint.get("setup_complete"):
        page.goto(
            checkpoint["ticket_url"],
            wait_until="domcontentloaded",
            timeout=SLOW_ODOO_TIMEOUT,
        )
        _ensure_ticket_setup(
            page, checkpoint, progress_callback, checkpoint_callback,
        )
    return _process_return_groups(
        page=page,
        order_id=_text(order_id),
        returned_products=returned_products,
        checkpoint=checkpoint,
        progress_callback=progress_callback,
        force_ticket_reload=True,
        checkpoint_callback=checkpoint_callback,
    )




def _verify_recorded_transfer_identity(page, checkpoint: dict,
                                       pending: dict) -> dict:
    """Verify a recovery transfer without inspecting Draft/Ready/Done.

    Requires the exact recorded TC/IN plus a matching Helpdesk link and/or
    source delivery. No validation or quantity changes occur here.
    """
    wanted_id = _text(pending.get('transfer_id'))
    actual = _capture_transfer(page)
    if actual['transfer_id'] != wanted_id:
        raise RuntimeError(
            f'Existing transfer mismatch: recorded {wanted_id}, '
            f'but Odoo opened {actual["transfer_id"]}. Nothing changed.'
        )

    verified_ticket = False
    expected_ticket_path = urlsplit(
        _text(checkpoint.get('ticket_url'))
    ).path.rstrip('/')
    # Compact Odoo stock forms sometimes show only a back ARROW, no ticket
    # link. The nested URL still carries a concrete Helpdesk association.
    # Use path segments, not substring matching (ticket 3699 != 36990).
    current_path = urlsplit(_text(page.url)).path.rstrip('/')
    nested = re.search(
        r'^(/odoo/helpdesk/\d+/tickets/\d+)/stock\.picking/\d+$',
        current_path, re.I,
    )
    if nested:
        if nested.group(1) != expected_ticket_path:
            raise RuntimeError(
                f'Transfer {wanted_id} URL links to a different '
                'Helpdesk ticket. Do not modify this transfer.'
            )
        verified_ticket = True
    back_links = page.locator(
        'li.o_back_button a[href*="/odoo/helpdesk/3/tickets/"]'
    )
    if back_links.count():
        seen = [urlsplit(_text(href)).path.rstrip('/')
                for href in back_links.evaluate_all(
                    'links => links.map(a => a.getAttribute("href") || "")'
                )]
        if expected_ticket_path not in seen:
            raise RuntimeError(
                f'Transfer {wanted_id} links to a different Helpdesk ticket.'
            )
        verified_ticket = True

    verified_source = False
    expected_delivery = _text(pending.get('delivery_to_return'))
    if expected_delivery:
        origin = page.locator('div[name="origin"] input').first
        origin_value = _text(origin.input_value(timeout=DEFAULT_TIMEOUT))
        if origin_value:
            if origin_value not in (expected_delivery,
                                    f'Return of {expected_delivery}'):
                raise RuntimeError(
                    f'Transfer {wanted_id} has a different source delivery: '
                    f'{origin_value!r}, expected {expected_delivery!r}.'
                )
            verified_source = True

    if not (verified_ticket or verified_source):
        raise RuntimeError(
            f'Transfer {wanted_id} cannot be tied to the saved ticket or '
            'delivery. Manual review required.'
        )
    return actual

def recover_existing_odoo_draft(
    context,
    order_id: str,
    returned_products: list[dict],
    checkpoint: dict,
    progress_callback=None,
    checkpoint_callback=None,
) -> dict:
    """Recover a recorded TC/IN using business evidence, not its stock status.

    No additional Return is created. An already-submitted Grant Approval
    handoff is recognized without editing or revalidating that transfer.
    If validation may have been sent but no independent confirmation exists,
    retain Manual Review instead of clicking Validate again.
    """
    if not checkpoint or checkpoint.get("resume_safe", True):
        raise RuntimeError(
            "Existing-draft recovery requires a manual-review-only checkpoint."
        )
    if _text(checkpoint.get("order_id")) != _text(order_id):
        raise RuntimeError("Checkpoint Order ID does not match the loaded order.")
    if not _TICKET_URL_RE.fullmatch(_text(checkpoint.get("ticket_url"))):
        raise RuntimeError("Checkpoint has no verified Helpdesk ticket URL.")
    pending = checkpoint.get("pending_return") or {}
    transfer_id = _text(pending.get("transfer_id"))
    transfer_url = _text(pending.get("transfer_url"))
    if not _TRANSFER_ID_RE.fullmatch(transfer_id) or not transfer_url:
        raise RuntimeError(
            "The checkpoint does not identify an existing transfer. "
            "Do not create a replacement; inspect the stock moves manually."
        )
    parsed = urlsplit(transfer_url)
    if (parsed.scheme != "https"
            or parsed.hostname != "makerlab.odoo.com"
            or not (parsed.path == "/odoo" or parsed.path.startswith("/odoo/"))):
        raise RuntimeError("Recorded transfer URL is not a recognized Odoo URL.")

    groups = _build_return_groups(returned_products)
    index = int(pending.get("return_index") or 0)
    if not 1 <= index <= len(groups):
        raise RuntimeError("Invalid pending Return group index in checkpoint.")
    if int(checkpoint.get("next_return_index") or 0) != index:
        raise RuntimeError("Pending Return index and checkpoint progress disagree.")
    if len(checkpoint.get("returns") or []) != index - 1:
        raise RuntimeError("Completed return group count is inconsistent.")
    group = groups[index - 1]
    for field in ("decision", "classification", "status"):
        if _text(pending.get(field)) != _text(group[field]):
            raise RuntimeError(f"Pending Return {field} differs from confirmed items.")
    desired = _requested_return_quantities(group["items"])
    recorded_items = _requested_return_quantities(pending.get("items") or [])
    if desired != recorded_items:
        raise RuntimeError(
            "Saved pending SKUs/quantities differ from confirmed items. "
            "No stock transfer was modified."
        )

    # A post-warning checkpoint can only arise after the FIRST Validate.
    # Reject inconsistent or manually tampered recovery markers, rather than
    # interpreting them as permission to validate an unrelated transfer.
    if (pending.get('zero_demand_keep_lines_confirmed')
            or pending.get('post_keep_lines_second_validate_in_flight')):
        if (group['classification'] != 'New'
                or not pending.get('validation_action_in_flight')):
            raise RuntimeError(
                'Invalid post-Keep-lines recovery checkpoint. Existing '
                'transfer requires Manual Review; no Validate attempted.'
            )

    original_stage = _text(checkpoint.get('stage'))
    page = get_or_open_odoo_page(context)
    page.bring_to_front()
    _progress(progress_callback,
              f"Opening recorded transfer {transfer_id} (no new Return)...")
    page.goto(transfer_url, wait_until="domcontentloaded",
              timeout=SLOW_ODOO_TIMEOUT)
    _verify_recorded_transfer_identity(page, checkpoint, pending)

    # Save the manual-review marker again BEFORE any edit. A crash at any
    # subsequent stage must never turn this into a safe-to-create-new-return.
    checkpoint["stage"] = "existing_draft_recovery_in_flight"
    checkpoint["resume_safe"] = False
    _checkpoint(checkpoint_callback, checkpoint, "manual_review")

    has_warehouse_handoff = (
        group['classification'] == 'New'
        and _wait_for_existing_handoff(page)
    )
    if has_warehouse_handoff:
        # The warehouse already received the request. Editing the picking
        # or pressing Validate again risks changing or duplicating its work.
        _verify_operation_demands(page, desired)
        _existing_new_stock_destination_verified(
            page, checkpoint.get('new_stock_destination', 'MNL/Stock')
        )
        _progress(progress_callback,
                  f'Warehouse approval already requested for {transfer_id}; '
                  'no edits or repeat Validate.')
    else:
        # v1.0.3.5 lacked a pre-Validate checkpoint. Older uncertain cases
        # without a visible handoff cannot safely be validated blindly.
        old_boundary = int(pending.get('validation_boundary_version') or 0) < 2
        if (old_boundary
                and original_stage not in {'return_draft_created'}
                and not pending.get('validation_action_in_flight')):
            raise RuntimeError(
                f'Existing {transfer_id} was processed by an older version '
                'that cannot prove Validate was not already clicked. '
                'Warehouse activity/QC completion is not confirmed. Keep Manual '
                'Review; do not click Validate again.'
            )
        resume_after_keep_lines = False
        if pending.get('validation_action_in_flight'):
            if group['classification'] == 'New':
                if pending.get('post_keep_lines_second_validate_in_flight'):
                    raise RuntimeError(
                        f'The post-Keep-lines second Validate may already have '
                        f'been sent for {transfer_id}. Keep Manual Review; '
                        'do not click Validate a third time.'
                    )
                if pending.get('zero_demand_keep_lines_confirmed'):
                    # Only a persisted confirmation from the upgraded module
                    # allows the second phase on an existing TC/IN. Old
                    # uncertain checkpoints remain locked.
                    resume_after_keep_lines = True
                    _verify_operation_demands(page, desired)
                    _existing_new_stock_destination_verified(
                        page, checkpoint.get('new_stock_destination', 'MNL/Stock')
                    )
                else:
                    raise RuntimeError(
                        f'Validate may already have been sent for {transfer_id}, '
                        'but no verified Keep lines checkpoint or warehouse '
                        'handoff is saved. Keep Manual Review; do not retry '
                        'Validate automatically.'
                    )
            if group['classification'] == 'New':
                skip_validate = True  # Only the guarded second phase is allowed.
            else:
                # A pending QC modal proves the previous Validate started.
                expected_qc = set(desired)
                active = page.locator(
                    'div[role="dialog"], .modal-content'
                ).filter(has_text=re.compile(r'TECHNICAL\s+RETURN\s+QC', re.I))
                if not any(active.nth(i).is_visible()
                           for i in range(active.count())):
                    raise RuntimeError(
                        f'Validate may have been sent for {transfer_id}, but '
                        'no QC dialog is open. Do not revalidate automatically.'
                    )
                skip_validate = True
        else:
            skip_validate = False
            _progress(progress_callback,
                      f'Confirming Demand on existing {transfer_id}...')
            _set_quantities_on_draft_transfer(
                page, group['items'],
                # Compatibility with v1.0.5.2: older checkpoints only
                # recorded delivery_to_return='' and not this new flag.
                manual_stock_entry=bool(pending.get(
                    'manual_stock_entry_required',
                    not bool(_text(pending.get('delivery_to_return'))),
                )),
                order_id=order_id,
                platform=checkpoint.get('platform', 'Shopee'),
            )
            _verify_recorded_transfer_identity(page, checkpoint, pending)
            checkpoint['stage'] = 'return_demand_verified'
            checkpoint['resume_safe'] = False
            _checkpoint(checkpoint_callback, checkpoint, 'manual_review')

    def before_validate():
        pending['validation_action_in_flight'] = True
        checkpoint['pending_return'] = pending
        checkpoint['stage'] = 'return_validation_action_in_flight'
        checkpoint['resume_safe'] = False
        _checkpoint(checkpoint_callback, checkpoint, 'manual_review')

    def on_keep_lines():
        pending['validation_action_in_flight'] = True
        pending['zero_demand_keep_lines_confirmed'] = True
        checkpoint['pending_return'] = pending
        if not pending.get('post_keep_lines_second_validate_in_flight'):
            checkpoint['stage'] = 'return_zero_demand_keep_lines_confirmed'
        checkpoint['resume_safe'] = False
        _checkpoint(checkpoint_callback, checkpoint, 'manual_review')

    def before_second_validate():
        if not pending.get('zero_demand_keep_lines_confirmed'):
            raise RuntimeError('Missing verified Keep lines checkpoint.')
        if pending.get('post_keep_lines_second_validate_in_flight'):
            raise RuntimeError('Second Validate already attempted. Manual Review.')
        pending['post_keep_lines_second_validate_in_flight'] = True
        checkpoint['pending_return'] = pending
        checkpoint['stage'] = 'return_post_keep_lines_second_validate_in_flight'
        checkpoint['resume_safe'] = False
        _checkpoint(checkpoint_callback, checkpoint, 'manual_review')

    if group['classification'] == 'New':
        stock_result = _process_brand_new(
            page, before_validate=before_validate, items=group['items'],
            destination=checkpoint.get('new_stock_destination', 'MNL/Stock'),
            on_keep_lines=on_keep_lines,
            before_second_validate=before_second_validate,
            resume_after_keep_lines=bool(
                pending.get('zero_demand_keep_lines_confirmed')
                and not pending.get('post_keep_lines_second_validate_in_flight')
            ),
        )
    else:
        stock_result = _process_open_box_or_defective(
            page, group['items'], before_validate=before_validate,
            skip_validate=skip_validate,
        )
    if stock_result.get("transfer_id") != transfer_id:
        raise RuntimeError("Recovered transfer ID differs from saved TC/IN ID.")

    result = {
        "return_index": index,
        "decision": group["decision"],
        "classification": group["classification"],
        "status": group["status"],
        "items": [
            {"sku": _text(item["sku"]), "quantity": int(item["quantity"])}
            for item in group["items"]
        ],
        **stock_result,
    }
    checkpoint["returns"] = list(checkpoint.get("returns") or []) + [result]
    checkpoint["next_return_index"] = index + 1
    checkpoint.pop("pending_return", None)
    unresolved = _pending_group_validation(checkpoint['returns'])
    checkpoint['pending_warehouse_approval_transfer_ids'] = (
        _warehouse_approval_pending_ids(checkpoint['returns'])
    )
    if unresolved:
        checkpoint["stage"] = "return_created_waiting_validation"
        checkpoint["resume_safe"] = False
        checkpoint["pending_validation_transfer_ids"] = [
            r["transfer_id"] for r in unresolved
        ]
        _checkpoint(checkpoint_callback, checkpoint, "manual_review")
        _progress(progress_callback,
                  f"Existing {transfer_id} is awaiting Odoo validation/QC; "
                  "additional classification drafts may be prepared.")
    else:
        checkpoint.pop('pending_validation_transfer_ids', None)
        checkpoint["stage"] = (
            'warehouse_handoff_requested'
            if checkpoint['pending_warehouse_approval_transfer_ids']
            else "return_group_completed"
        )
        checkpoint["resume_safe"] = True
        _checkpoint(checkpoint_callback, checkpoint, "odoo_ticket_ready")
        milestone = (
            'QC confirmation.' if stock_result.get('qc_completed')
            else 'warehouse handoff.' if stock_result.get('warehouse_handoff_complete')
            else 'processing.'
        )
        _progress(progress_callback,
                  f'Existing transfer {transfer_id} checkpointed after {milestone}')

    # The existing group is complete; only later groups may create Returns.
    return _process_return_groups(
        page=page,
        order_id=_text(order_id),
        returned_products=returned_products,
        checkpoint=checkpoint,
        progress_callback=progress_callback,
        force_ticket_reload=True,
        checkpoint_callback=checkpoint_callback,
    )


def create_odoo_tickets(
    context,
    order_id: str,
    returned_products: list[dict],
    case_decision: dict | None = None,
    platform: str = "Shopee",
    progress_callback=None,
    checkpoint_callback=None,
    new_stock_destination: str = 'MNL/Stock',
) -> dict:
    """
    Create one Helpdesk ticket for a marketplace order and one or more stock
    returns grouped by Decision + Classification + Status.

    If the source Sales Order is not yet available for Return, raise a
    checkpoint-bearing OdooWorkflowPausedError. The caller can later invoke
    resume_odoo_returns() without creating a duplicate Helpdesk ticket.
    """
    new_stock_destination = _validated_new_stock_destination(new_stock_destination)
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
    _set_basic_ticket_fields(page, ticket_title, platform)

    # Two-phase checkpoint: an unsafe creation-in-progress record is saved
    # BEFORE clicking Add. If the browser dies during Add, the operator must
    # inspect Odoo instead of risking a duplicate Helpdesk ticket.
    checkpoint = _base_checkpoint(
        order_id=order_id,
        ticket_title=ticket_title,
        ticket_url="",
        first_sku=first_sku,
        tags=tags,
        platform=platform,
        new_stock_destination=new_stock_destination,
    )
    _checkpoint(checkpoint_callback, checkpoint, "manual_review")

    def ticket_created(ticket_url):
        checkpoint["ticket_url"] = ticket_url
        checkpoint["stage"] = "ticket_created"
        checkpoint["resume_safe"] = True
        _checkpoint(checkpoint_callback, checkpoint, "odoo_ticket_created")

    _progress(progress_callback, "Saving new Odoo ticket...")
    _create_and_open_ticket(page, ticket_title, on_created=ticket_created)
    _ensure_ticket_setup(
        page, checkpoint, progress_callback, checkpoint_callback,
    )

    return _process_return_groups(
        page=page,
        order_id=order_id,
        returned_products=returned_products,
        checkpoint=checkpoint,
        progress_callback=progress_callback,
        force_ticket_reload=False,
        checkpoint_callback=checkpoint_callback,
    )




def _reconcile_odoo_transfer_link(
    transfer_url: str,
    ticket_number: str,
    *,
    operator_attested: bool = False,
) -> dict:
    """Validate Odoo stock-transfer links without assuming one router layout.

    A link that explicitly names another Helpdesk ticket is NEVER accepted.
    When the link does not embed any ticket ID, only a separately verified
    manual-entry checkpoint may use the actual Odoo stock.picking route.
    This distinction is carried into the audit; no live Odoo verification is
    claimed by this URL-only check.
    """
    transfer_url = _text(transfer_url)
    parsed = urlsplit(transfer_url)
    if (parsed.scheme != 'https' or
            parsed.hostname != 'makerlab.odoo.com' or
            parsed.username is not None or parsed.password is not None):
        raise ValueError('Transfer link must use https://makerlab.odoo.com.')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Transfer link has an invalid port.') from exc
    if port not in (None, 443):
        raise ValueError('Transfer link must use the standard Odoo HTTPS port.')

    path = parsed.path.rstrip('/') or '/'
    expected_ticket = _text(ticket_number)
    # Check ALL explicit Helpdesk identifiers, even if the current URL route
    # is otherwise valid; this prevents a different-ticket path from being
    # treated as an alternate stock-transfer route.
    path_refs = re.findall(r'/odoo/helpdesk/(\d+)/tickets/(\d+)(?=/|$)', path)
    if any(team != '3' or record != expected_ticket for team, record in path_refs):
        raise ValueError(
            f'Transfer URL does not belong to Helpdesk #{expected_ticket}: '
            'it explicitly references another Helpdesk ticket.'
        )

    parameters = parse_qs(parsed.query, keep_blank_values=False)
    fragments = parse_qs(parsed.fragment, keep_blank_values=False)
    for key in ('ticket_id', 'helpdesk_ticket_id', 'helpdesk_id'):
        references = parameters.get(key, []) + fragments.get(key, [])
        if any(not re.fullmatch(r'0*' + re.escape(expected_ticket), ref)
               for ref in references):
            raise ValueError(
                f'Transfer URL {key} references a different Helpdesk ticket.'
            )

    model_path = re.fullmatch(
        r'/odoo(?:/[A-Za-z0-9._~%-]+)*/stock\.picking/([1-9]\d*)', path
    )
    route_id = model_path.group(1) if model_path else None
    if route_id is None:
        # Older Odoo links encode model/id in query or fragment. They must
        # name stock.picking explicitly; a bare Helpdesk URL is insufficient.
        for kv in (parameters, fragments):
            models = kv.get('model', [])
            ids = kv.get('id', []) + kv.get('res_id', [])
            if ('stock.picking' in models and len(ids) == 1 and
                    re.fullmatch(r'[1-9]\d*', ids[0]) and
                    (path == '/web' or path == '/odoo' or path.startswith('/odoo/'))):
                route_id = ids[0]
                break

    if route_id is None:
        raise ValueError(
            'Transfer link is not a recognized Makerlab Odoo stock.picking '
            'record URL. Copy the transfer page address (not the Helpdesk '
            'ticket address) and try again.'
        )
    embedded_ticket = bool(path_refs)
    if not embedded_ticket and not operator_attested:
        raise ValueError(
            'Transfer URL uses an alternate Odoo route without an embedded '
            'Helpdesk ticket number. Manual ticket-association confirmation '
            'is required before filing Lark.'
        )
    return {
        'stock_picking_record_id': route_id,
        'ticket_association_method': (
            'helpdesk_ticket_id_embedded_in_url' if embedded_ticket
            else 'operator_attested_alternate_odoo_route'
        ),
        'ticket_association_verified_by_url': embedded_ticket,
    }


def confirm_existing_transfers_for_lark(
    *,
    checkpoint: dict,
    order_id: str,
    returned_products: list[dict],
    confirmed_transfer_id: str,
) -> dict:
    """Operator-reviewed, checkpoint-only reconciliation. NEVER visits Odoo.

    This deliberately does not infer stock validation from Draft/Ready/Done.
    The operator must independently inspect *all* recorded transfers, their
    SKUs/quantities and applicable warehouse handoff/QC before using this.
    Missing or mismatched transfer groups fail closed instead of filing Lark.
    """
    if not isinstance(checkpoint, dict) or not checkpoint:
        raise ValueError('No Odoo checkpoint was provided.')
    order_id = _text(order_id)
    if not order_id or _text(checkpoint.get('order_id')) != order_id:
        raise ValueError('Saved Odoo checkpoint belongs to another Order ID.')

    ticket_url = _text(checkpoint.get('ticket_url'))
    parsed_ticket = urlsplit(ticket_url)
    ticket_match = re.fullmatch(
        r'/odoo/helpdesk/3/tickets/(\d+)/?', parsed_ticket.path
    )
    if (parsed_ticket.scheme != 'https' or
            parsed_ticket.hostname != 'makerlab.odoo.com' or
            not ticket_match):
        raise ValueError('Checkpoint has no valid Makerlab Helpdesk URL.')
    ticket_number = ticket_match.group(1)

    groups = _build_return_groups(returned_products)
    if not groups:
        raise ValueError('There are no physically returned items to reconcile.')
    allowed_classifications = {'New', 'Unsealed', 'Defective'}
    if any(group['classification'] not in allowed_classifications or
           group['status'] != 'Returned' for group in groups):
        raise ValueError('A return group has unsupported classification/status.')

    saved_returns = list(checkpoint.get('returns') or [])
    pending = checkpoint.get('pending_return') or {}
    if pending and not isinstance(pending, dict):
        raise ValueError('Pending Return checkpoint must be an object.')
    if pending:
        if len(saved_returns) + 1 != len(groups):
            raise ValueError(
                'Other return classifications are still missing transfer IDs. '
                'Create/reconcile each required TC/IN before Lark filing.'
            )
        if int(checkpoint.get('next_return_index') or 0) != len(groups):
            raise ValueError('Pending Return position is inconsistent with items.')
        saved_returns.append(pending)
    elif len(saved_returns) != len(groups):
        raise ValueError(
            'The number of recorded TC/IN transfers does not match the '
            'confirmed classification groups. Do not bypass Odoo.'
        )

    final_results = []
    seen_ids = set()
    stamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    destination = _validated_new_stock_destination(
        checkpoint.get('new_stock_destination', 'MNL/Stock')
    )
    for index, (group, saved) in enumerate(zip(groups, saved_returns), 1):
        if not isinstance(saved, dict):
            raise ValueError(f'Return group {index} is not a valid checkpoint.')
        if int(saved.get('return_index') or 0) != index:
            raise ValueError(f'Return group #{index} has an inconsistent index.')
        for name in ('decision', 'classification', 'status'):
            if _text(saved.get(name)) != _text(group[name]):
                raise ValueError(
                    f'Return #{index} {name} differs from confirmed item decisions.'
                )
        desired = _requested_return_quantities(group['items'])
        recorded = _requested_return_quantities(saved.get('items') or [])
        if not desired or desired != recorded:
            raise ValueError(
                f'Return #{index} has different SKU/quantity from the saved '
                'checkpoint. Do not file Lark until reconciled.'
            )
        transfer_id = _text(saved.get('transfer_id'))
        transfer_url = _text(saved.get('transfer_url'))
        if not _TRANSFER_ID_RE.fullmatch(transfer_id) or transfer_id in seen_ids:
            raise ValueError(f'Return #{index} has a missing/duplicate TC/IN ID.')
        seen_ids.add(transfer_id)
        try:
            association = _reconcile_odoo_transfer_link(
                transfer_url,
                ticket_number,
                operator_attested=bool(
                    isinstance(checkpoint.get('manual_entry'), dict) and
                    checkpoint['manual_entry'].get(
                        'operator_acknowledged_manual_completion') is True
                ),
            )
        except ValueError as exc:
            raise ValueError(f'Return #{index}: {exc}') from exc
        recorded_result = copy.deepcopy(saved)
        recorded_result['items'] = [
            {'sku': _text(item['sku']), 'quantity': int(item['quantity'])}
            for item in group['items']
        ]
        recorded_result['return_index'] = index
        recorded_result['transfer_id'] = transfer_id
        recorded_result['transfer_url'] = transfer_url
        recorded_result.update(association)
        recorded_result['manual_verified_for_lark'] = True
        recorded_result['manual_verified_at'] = stamp
        recorded_result['manual_verification_source'] = 'operator_confirmation'
        # Never present a human assertion as a machine-verified stock posting.
        recorded_result['validated'] = bool(saved.get('validated', False))
        recorded_result['stock_state'] = saved.get('stock_state') or 'not_checked'
        if group['classification'] == 'New':
            recorded_result['destination_location'] = destination
            recorded_result['warehouse_handoff_complete'] = True
            recorded_result['warehouse_handoff_signal'] = (
                saved.get('warehouse_handoff_signal') or 'operator_confirmed'
            )
            recorded_result.setdefault('validation_pending', True)
        else:
            recorded_result['qc_completed'] = True
            recorded_result['qc_confirmation_source'] = 'operator_confirmation'
            recorded_result['validation_pending'] = False
        final_results.append(recorded_result)

    requested_id = _text(confirmed_transfer_id)
    if requested_id != final_results[-1]['transfer_id']:
        raise ValueError(
            'The typed TC/IN ID did not match the last saved return transfer.'
        )

    result = copy.deepcopy(checkpoint)
    result['returns'] = final_results
    result['next_return_index'] = None
    result.pop('pending_return', None)
    result.pop('pending_validation_transfer_ids', None)
    result['stage'] = 'returns_complete_operator_verified_for_lark'
    result['resume_safe'] = False
    result['manual_lark_reconciliation'] = {
        'confirmed_at': stamp,
        'method': 'operator_confirmation',
        'confirmed_transfer_id': requested_id,
        'confirmed_transfer_ids': [r['transfer_id'] for r in final_results],
        'ticket_association_methods': [
            r['ticket_association_method'] for r in final_results
        ],
        'note': (
            'Operator confirmed existing Odoo transfers and necessary '
            'warehouse handoff/QC; the processor did not repeat Odoo actions.'
        ),
    }
    return result


__all__ = [
    "build_ticket_title",
    "get_or_open_odoo_page",
    "create_odoo_tickets",
    "resume_odoo_returns",
    "recover_existing_odoo_draft",
    "confirm_existing_transfers_for_lark",
    "OdooWorkflowPausedError",
]
