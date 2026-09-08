from playwright.sync_api import sync_playwright


PROFILE = r"C:\PlaywrightPAD\OdooProfile"


class BrowserManager:
    def get_shopee_return_page(self):
        """
        Find the Shopee Return/Refund list page.
        If it is not open, open it automatically.
        """

        if not self.context:
            return None

        # First check existing tabs
        for page in self.context.pages:

            if page.is_closed():
                continue

            live_url = self.get_live_url(page)

            if "/portal/sale/returnrefundcancel" in live_url:
                return page

        # Not found -> open it automatically
        page = self.context.new_page()

        page.goto(
            "https://seller.shopee.ph/portal/sale/returnrefundcancel",
            wait_until="domcontentloaded"
        )

        return page

    def get_live_url(self, page):
        """
        Ask the browser for its actual current URL
        instead of relying only on Playwright's cached page.url.
        """

        try:
            # This also gives Playwright a chance to process browser events.
            page.wait_for_timeout(100)

            return page.evaluate(
                "() => window.location.href"
            )

        except Exception:
            return page.url
    
    def get_all_pages(self):
        if not self.context:
            return []

        return [
            page
            for page in self.context.pages
            if not page.is_closed()
        ]

    def __init__(self):
        self.playwright = None
        self.context = None

    def start(self):
        """
        Start Chrome using the persistent logged-in profile
        and open the Shopee Return/Refund page immediately.
        """

        self.playwright = sync_playwright().start()

        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--start-maximized"]
        )

        RETURN_LIST_URL = (
            "https://seller.shopee.ph/portal/sale/returnrefundcancel"
        )

        # Reuse the initial blank tab if one exists
        if self.context.pages:

            page = self.context.pages[0]

        else:

            page = self.context.new_page()

        # Open Shopee Return List instead of leaving about:blank
        if page.url == "about:blank":

            page.goto(
                RETURN_LIST_URL,
                wait_until="domcontentloaded"
            )

        return page

    def stop(self):
        """Close browser cleanly."""

        if self.context:
            self.context.close()

        if self.playwright:
            self.playwright.stop()

    def get_shopee_order_pages(self):

        if not self.context:
            return []

        pages = []

        for page in self.context.pages:

            if page.is_closed():
                continue

            live_url = self.get_live_url(page)

            print("CHECKING URL:", live_url)

            if "/portal/sale/order/" in live_url:
                pages.append(page)

        return pages

    def open_shopee_order(self, url):
        """
        Open a Shopee Order URL.

        Reuses an about:blank page when possible,
        otherwise creates a new tab.
        """

        if not self.context:
            raise RuntimeError("Browser is not running.")

        url = url.strip()

        if "/portal/sale/order/" not in url:
            raise ValueError(
                "This does not appear to be a Shopee Order page URL."
            )

        # Reuse about:blank if one exists
        page = None

        for existing_page in self.context.pages:

            if existing_page.is_closed():
                continue

            live_url = self.get_live_url(existing_page)

            if live_url == "about:blank":
                page = existing_page
                break

        # Otherwise create new tab
        if page is None:
            page = self.context.new_page()

        page.goto(
            url,
            wait_until="domcontentloaded"
        )

        page.bring_to_front()

        return page