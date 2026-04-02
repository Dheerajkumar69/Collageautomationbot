from playwright.sync_api import Page, TimeoutError
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
            LoginSelectors.USERNAME_INPUT_FALLBACK
        ])
        
        # Password: try multiple selectors
        pass_input = safe_locator_or(self.page, [
            LoginSelectors.PASSWORD_INPUT,
            LoginSelectors.PASSWORD_INPUT_FALLBACK
        ])
        
        # Login button: try multiple selectors
        login_btn = safe_locator_or(self.page, [
            LoginSelectors.LOGIN_BTN,
            LoginSelectors.LOGIN_BTN_FALLBACK
        ])
        
        safe_fill(user_input, self.config.username)
        safe_fill(pass_input, self.config.password)
        safe_click(login_btn)

    def _verify_login(self):
        logger.debug("Verifying login via Sidebar element presence...")
        try:
            # Try to find Feedback link (indicates we're logged in)
            feedback_link = safe_locator_or(self.page, [
                SidebarSelectors.FEEDBACK_LINK,
                SidebarSelectors.FEEDBACK_LINK_FALLBACK_1,
                SidebarSelectors.FEEDBACK_LINK_FALLBACK_2
            ])
            feedback_link.first.wait_for(state="visible", timeout=15000)
        except TimeoutError:
            raise LoginFailedError("Dashboard Sidebar not detected after login.")
