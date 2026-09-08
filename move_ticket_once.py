from playwright.sync_api import sync_playwright
import re


ODOO_URL = "https://makerlab.odoo.com/odoo/helpdesk/3/tickets"

# Change this to the ticket you want to move
TICKET_TITLE = "Order ID: 02251-001-0004 - Replacement"

# You can point this to an existing Playwright Chrome profile
PROFILE_DIR = r"C:\PlaywrightPAD\OdooProfile"


with sync_playwright() as p:

    context = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        channel="chrome",
        headless=False,
        no_viewport=True,
        args=["--start-maximized"],
    )

    page = context.pages[0]

    print("Opening Odoo...")

    page.goto(
        ODOO_URL,
        wait_until="domcontentloaded"
    )

    page.locator(
        ".o_kanban_renderer"
    ).wait_for(
        state="visible",
        timeout=30000
    )

    # =====================================================
    # FIND NEW COLUMN
    # =====================================================

    new_column = (
        page.locator(".o_kanban_group")
        .filter(
            has=page.locator(
                ".o_column_title",
                has_text=re.compile(r"^\s*New\s*$")
            )
        )
        .first
    )

    # =====================================================
    # FIND TICKET
    # =====================================================

    ticket = (
        new_column
        .locator("article.o_kanban_record")
        .filter(
            has=page.locator(
                ".field_name",
                has_text=TICKET_TITLE
            )
        )
        .first
    )

    ticket.wait_for(
        state="visible",
        timeout=30000
    )

    print("Ticket found:")
    print(TICKET_TITLE)

    # =====================================================
    # FIND SOLVED COLUMN
    # =====================================================

    solved_column = (
        page.locator(".o_kanban_group")
        .filter(
            has=page.locator(
                ".o_column_title",
                has_text=re.compile(
                    r"^\s*Solved",
                    re.IGNORECASE
                )
            )
        )
        .first
    )

    solved_column.wait_for(
        state="visible",
        timeout=30000
    )

    print("Solved column found")

    # =====================================================
    # DRAG
    # =====================================================

    print("Dragging ticket...")

    ticket.scroll_into_view_if_needed()

    ticket.drag_to(
        solved_column,
        timeout=30000
    )

    page.wait_for_timeout(3000)

    print("Done.")

    input("Press ENTER to close...")

    context.close()