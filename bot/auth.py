from playwright.sync_api import Page
from .config import Config
from .logger import logger
from .selectors import LoginSelectors, SidebarSelectors
from .utils import with_retry, save_error_artifacts, safe_click, safe_fill, safe_locator_or

class LoginFailedError(Exception):
    pass

class AuthHandler:
    def __init__(self, page: Page, config: Config):
        self.page = page
        self.config = config

    def login(self):
        logger.info("Opening LMS login page...")
        try:
            self.page.goto(self.config.login_url, wait_until="networkidle", timeout=30000)
            self._perform_login()
            self._verify_login()
            logger.info("[SUCCESS] Login verified successfully.")
        except Exception as e:
            logger.error(f"Login failed: {e}")
            save_error_artifacts(self.page, "login_critical_failure")
            raise LoginFailedError("Failed to log in. Check credentials or network.") from e

    @with_retry(max_retries=3, delay=1.0)
    def _perform_login(self):
        logger.debug("Locating and filling credentials...")
        
        # Username: try multiple selectors via .or() chaining
        user_input = safe_locator_or(self.page, [
            LoginSelectors.USERNAME_INPUT,
            LoginSelectors.USERNAME_INPUT_FALLBACK,
            LoginSelectors.USERNAME_INPUT_FALLBACK_2,
            LoginSelectors.USERNAME_INPUT_FALLBACK_3,
        ], wait_timeout_ms=15000)
        
        # Password: try multiple selectors
        pass_input = safe_locator_or(self.page, [
            LoginSelectors.PASSWORD_INPUT,
            LoginSelectors.PASSWORD_INPUT_FALLBACK,
            LoginSelectors.PASSWORD_INPUT_FALLBACK_2,
        ], wait_timeout_ms=15000)
        
        # Login button: try multiple selectors
        login_btn = safe_locator_or(self.page, [
            LoginSelectors.LOGIN_BTN,
            LoginSelectors.LOGIN_BTN_FALLBACK,
            LoginSelectors.LOGIN_BTN_FALLBACK_2,
        ], wait_timeout_ms=15000)

        if user_input is None or pass_input is None or login_btn is None:
            raise LoginFailedError("Unable to locate login form elements.")

        safe_fill(user_input.first, self.config.username)
        safe_fill(pass_input.first, self.config.password)
        safe_click(login_btn.first)

    def _verify_login(self):
        logger.debug("Verifying login via URL transition and dashboard markers...")

        # Give the portal enough time to complete redirects and client-side rendering.
        self.page.wait_for_load_state("domcontentloaded", timeout=30000)
        self.page.wait_for_timeout(1200)

        current_url = self.page.url
        normalized_url = current_url.lower()

        if "/student/login" in normalized_url:
            login_error = safe_locator_or(self.page, [
                ".flash-message .alert",
                ".alert-danger",
                ".invalid-feedback",
                "text=Invalid credentials",
                "text=incorrect",
            ], wait_timeout_ms=2000)

            error_text = ""
            try:
                if login_error and login_error.count() > 0:
                    error_text = (login_error.first.text_content() or "").strip()
            except Exception:
                pass

            if error_text:
                raise LoginFailedError(f"Still on login page after submit. Portal message: {error_text}")
            raise LoginFailedError("Still on login page after submit.")

        dashboard_marker = safe_locator_or(self.page, [
            SidebarSelectors.FEEDBACK_LINK,
            SidebarSelectors.FEEDBACK_LINK_FALLBACK_1,
            SidebarSelectors.FEEDBACK_LINK_FALLBACK_2,
            SidebarSelectors.FEEDBACK_LINK_FALLBACK_3,
            SidebarSelectors.DASHBOARD_SIDEBAR,
            SidebarSelectors.FEEDBACK_DASHBOARD_TITLE,
            SidebarSelectors.DASHBOARD_GREETING_MORNING,
            SidebarSelectors.DASHBOARD_GREETING_AFTERNOON,
            SidebarSelectors.DASHBOARD_GREETING_EVENING,
        ], wait_timeout_ms=30000)

        if dashboard_marker and dashboard_marker.count() > 0:
            return

        if "/student/dashboard" in normalized_url:
            logger.warning("Dashboard URL detected without marker; proceeding with best-effort login success.")
            return

        raise LoginFailedError(f"Dashboard not detected after login. Current URL: {current_url}")
