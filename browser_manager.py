import time
from urllib.parse import urljoin

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# Keep the existing folder so current marketplace/Odoo/Lark logins are preserved.
# The same persistent Chrome profile stores Shopee, Lazada, and TikTok sessions.
PROFILE = r"C:\PlaywrightPAD\OdooProfile"

SHOPEE_RETURN_LIST_URL = (
    "https://seller.shopee.ph/portal/sale/returnrefundcancel"
)
LAZADA_RETURN_LIST_URL = (
    "https://sellercenter.lazada.com.ph/apps/order/reverse"
    "?returnTab=merchant&tab=ReturnInProgress"
)
TIKTOK_RETURN_LIST_URL = (
    "https://seller-ph.tiktok.com/order/return"
    "?order_sort_comp=OrderSort_UPADTE_TIME_DESC"
    "&sub_tab_pending=sub_tab_pending_all&tab=800"
)


class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.context = None

    def get_live_url(self, page):
        """Read the browser's current URL instead of relying only on page.url."""
        try:
            page.wait_for_timeout(100)
            return page.evaluate("() => window.location.href")
        except Exception:
            return page.url

    def get_all_pages(self):
        if not self.context:
            return []
        return [page for page in self.context.pages if not page.is_closed()]

    def _find_page(self, predicate):
        if not self.context:
            return None
        for page in self.context.pages:
            if page.is_closed():
                continue
            try:
                if predicate(self.get_live_url(page)):
                    return page
            except Exception:
                continue
        return None

    def _get_blank_page(self):
        if not self.context:
            return None
        return self._find_page(lambda url: url == "about:blank")

    def start(self):
        """
        Start Chrome with the shared persistent Makerlab processor profile.

        Existing behavior is preserved: the first blank tab opens Shopee's
        Return/Refund list. Lazada can then be opened in the same context, so a
        Lazada login performed there is saved in the same persistent profile.
        """
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            channel="chrome",
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
        )

        if self.context.pages:
            page = self.context.pages[0]
        else:
            page = self.context.new_page()

        if page.url == "about:blank":
            page.goto(
                SHOPEE_RETURN_LIST_URL,
                wait_until="domcontentloaded",
            )
        return page

    def stop(self):
        """Close browser and Playwright cleanly."""
        if self.context:
            self.context.close()
            self.context = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None

    # -----------------------------------------------------------------
    # Shopee
    # -----------------------------------------------------------------
    def get_shopee_return_page(self):
        """Find or open the Shopee Return/Refund list page."""
        if not self.context:
            return None

        page = self._find_page(
            lambda url: "/portal/sale/returnrefundcancel" in url
        )
        if page:
            return page

        page = self.context.new_page()
        page.goto(
            SHOPEE_RETURN_LIST_URL,
            wait_until="domcontentloaded",
        )
        return page

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
        """Open one Shopee Order URL in the persistent browser context."""
        if not self.context:
            raise RuntimeError("Browser is not running.")

        url = url.strip()
        if "/portal/sale/order/" not in url:
            raise ValueError("This does not appear to be a Shopee Order page URL.")

        page = self._get_blank_page() or self.context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.bring_to_front()
        return page


    def open_shopee_search_result(self, source_url, expected_order_id=""):
        """
        Open a Shopee Return List search result and end on Order Details.

        Shopee Return List rows are inconsistent: some link directly to
        /portal/sale/order/... while others link to /portal/sale/return/....
        For return-detail links, this follows the Order Details link exposed on
        that page and reuses the same tab.
        """
        if not self.context:
            raise RuntimeError("Browser is not running.")

        source_url = str(source_url or "").strip()
        if not source_url:
            raise ValueError("Shopee search result URL is empty.")

        if "/portal/sale/order/" in source_url:
            return self.open_shopee_order(source_url)

        if "/portal/sale/return/" not in source_url:
            raise ValueError(
                "Shopee search result is neither an Order nor Return Details URL."
            )

        page = self._get_blank_page() or self.context.new_page()
        page.goto(source_url, wait_until="domcontentloaded")
        page.bring_to_front()

        # Return Details normally exposes an Order Details breadcrumb/link.
        # Prefer any anchor that also contains the visible Order ID, then fall
        # back to the first Seller Center order link.
        order_link = None
        if expected_order_id:
            by_text = page.locator('a[href*="/portal/sale/order/"]').filter(
                has_text=expected_order_id
            ).first
            try:
                by_text.wait_for(state="attached", timeout=4_000)
                order_link = by_text
            except Exception:
                pass

        if order_link is None:
            candidate = page.locator('a[href*="/portal/sale/order/"]').first
            try:
                candidate.wait_for(state="attached", timeout=20_000)
                order_link = candidate
            except Exception as error:
                raise RuntimeError(
                    "Shopee Return Details opened, but its Order Details link "
                    "could not be found."
                ) from error

        href = str(order_link.get_attribute("href") or "").strip()
        if not href:
            raise RuntimeError("Shopee Order Details link has no URL.")

        order_url = urljoin(page.url, href)
        page.goto(order_url, wait_until="domcontentloaded")
        page.bring_to_front()
        return page

    # -----------------------------------------------------------------
    # Lazada
    # -----------------------------------------------------------------
    def _finish_lazada_login(self, page):
        """
        Lazada sometimes redirects Return Orders to its sign-up landing page.
        Click 'Log in' there (it opens a popup tab), then press the password
        login form's 'Login' only if Chrome already filled both credentials.

        Never read passwords for logging, never type/store a credential, and
        never attempt to solve CAPTCHA/OTP challenges automatically.
        Return the actual authenticated Return Orders Page (which may be a
        different tab from `page`).
        """
        return_input = '#filters[name="filters"]'
        signup_link_selector = 'a.to-login-link[data-spm="d_local_login"]'
        login_form_selector = 'form.Login-password-login'
        followed_signup_link = False
        login_was_clicked = False
        deadline = time.monotonic() + 45

        while time.monotonic() < deadline:
            if page.is_closed():
                raise RuntimeError(
                    "Lazada closed its login/return tab. Open Lazada again "
                    "and retry the scan."
                )

            try:
                if page.locator(return_input).is_visible():
                    return page

                signup_link = page.locator(signup_link_selector).first
                if signup_link.is_visible():
                    if followed_signup_link:
                        raise RuntimeError(
                            "Lazada redirected back to registration after login. "
                            "Complete the login manually and retry the scan."
                        )
                    followed_signup_link = True
                    # 'Log in' is an <a target='_blank'>, not the Login button.
                    # Without expect_popup, the processor keeps the wrong tab.
                    href = signup_link.get_attribute('href') or ''
                    try:
                        with page.expect_popup(timeout=8_000) as popup_info:
                            signup_link.click(timeout=8_000)
                        page = popup_info.value
                        page.wait_for_load_state(
                            'domcontentloaded', timeout=15_000
                        )
                    except PlaywrightTimeoutError:
                        # Alternate layouts may navigate the same tab, or a
                        # new tab may appear outside the popup event window.
                        existing_login_tab = self._find_page(
                            lambda url: (
                                'sellercenter.lazada.com.ph' in url
                                and '/apps/seller/login' in url
                            )
                        )
                        if existing_login_tab:
                            page = existing_login_tab
                        elif '/apps/seller/login' not in page.url and href:
                            page.goto(
                                urljoin(page.url, href),
                                wait_until='domcontentloaded',
                            )
                    continue

                login_form = page.locator(login_form_selector).first
                if login_form.is_visible():
                    if not login_was_clicked:
                        account = login_form.locator('#account').first
                        password = login_form.locator('#password').first
                        button = login_form.locator('button.login-button').first
                        # Chrome autofill can be asynchronous. Wait a short
                        # time for both values rather than clicking too early.
                        credentials_ready = False
                        for _ in range(30):
                            try:
                                credentials_ready = bool(
                                    account.input_value(timeout=500).strip()
                                    and password.input_value(timeout=500)
                                )
                            except PlaywrightError:
                                credentials_ready = False
                            if credentials_ready:
                                break
                            page.wait_for_timeout(200)
                        if not credentials_ready:
                            raise RuntimeError(
                                "Lazada's login page is open, but the saved "
                                "account/password were not both autofilled. "
                                "Please log in manually in Chrome, then "
                                "scan/search again."
                            )
                        if not button.is_enabled():
                            raise RuntimeError(
                                "Lazada Login is disabled or requires further "
                                "verification. Complete it manually in Chrome, "
                                "then scan/search again."
                            )
                        try:
                            button.click(timeout=8_000)
                        except PlaywrightError as error:
                            raise RuntimeError(
                                "Could not click Lazada Login. Complete login "
                                "manually in Chrome, then scan/search again."
                            ) from error
                        login_was_clicked = True
                        # Lazada usually redirects to the Return Orders URL
                        # supplied in the original registration/login link.
                        deadline = time.monotonic() + 35
                    page.wait_for_timeout(250)
                    continue

                # For a successful login redirected to the Seller Center
                # landing page instead of Return Orders, navigate back once.
                # Do not navigate during verification or CAPTCHA challenges.
                url = page.url.lower()
                if login_was_clicked and any(
                    route in url for route in (
                        '/apps/home', '/seller/home', '/apps/dashboard'
                    )
                ):
                    page.goto(
                        LAZADA_RETURN_LIST_URL,
                        wait_until='domcontentloaded',
                    )
                    login_was_clicked = False
                    continue

                page.wait_for_timeout(250)
            except PlaywrightError:
                # Lazada may replace the document during a redirect.
                page.wait_for_timeout(250)

        if login_was_clicked:
            raise RuntimeError(
                "Clicked Lazada Login, but Return Orders did not open. "
                "Check the Chrome tab for an OTP, CAPTCHA, or login error; "
                "complete it manually, then scan/search again."
            )
        raise RuntimeError(
            "Lazada Return Orders did not finish loading. Check the Lazada "
            "Chrome tab, complete any login prompt, then scan/search again."
        )

    def get_lazada_return_page(self):
        """
        Find or open Lazada Seller Center's Return Orders page.

        The page uses the same persistent Chrome profile as Shopee/Odoo/Lark,
        so logging into Lazada once through this browser normally persists.
        """
        if not self.context:
            return None

        exact = self._find_page(
            lambda url: (
                "sellercenter.lazada.com.ph" in url
                and "/apps/order/reverse" in url
            )
        )
        if exact:
            page = exact
        else:
            # If Seller Center already has a login or registration tab, reuse
            # it to retain Chrome's saved-login context.
            lazada_page = self._find_page(
                lambda url: "sellercenter.lazada.com.ph" in url
            )
            page = lazada_page or self._get_blank_page() or self.context.new_page()
            page.goto(
                LAZADA_RETURN_LIST_URL,
                wait_until="domcontentloaded",
            )

        # Returns can redirect to /apps/register/registration. That page's
        # 'Log in' opens another tab, which must be followed to avoid trying
        # to search the original registration tab.
        page = self._finish_lazada_login(page)
        page.bring_to_front()
        return page


    # -----------------------------------------------------------------
    # TikTok
    # -----------------------------------------------------------------
    def get_tiktok_return_page(self):
        """Find or open TikTok Seller Center's Manage returns page."""
        if not self.context:
            return None

        exact = self._find_page(
            lambda url: (
                "seller-ph.tiktok.com" in url
                and "/order/return" in url
            )
        )
        if exact:
            return exact

        # Reuse any existing TikTok Seller Center tab so that login or
        # verification can be completed in the same persistent profile.
        tiktok_page = self._find_page(
            lambda url: "seller-ph.tiktok.com" in url
        )
        page = tiktok_page or self._get_blank_page() or self.context.new_page()
        page.goto(
            TIKTOK_RETURN_LIST_URL,
            wait_until="domcontentloaded",
        )
        page.bring_to_front()
        return page



__all__ = [
    "BrowserManager",
    "PROFILE",
    "SHOPEE_RETURN_LIST_URL",
    "LAZADA_RETURN_LIST_URL",
    "TIKTOK_RETURN_LIST_URL",
]
