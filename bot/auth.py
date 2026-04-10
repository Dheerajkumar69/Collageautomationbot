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
            # Use domcontentloaded — LMS 3rd-party analytics block networkidle for 3–8 s.
            self.page.goto(self.config.login_url, wait_until="domcontentloaded", timeout=30000)
            self._perform_login()
            self._verify_login()
            name = self._extract_student_name()
            if name:
                # Structured line parsed by server.py to populate queue display.
                logger.info(f"[BOT_META] student_name={name}")
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

        # Wait for the login redirect to complete — resolves immediately on URL change
        # instead of always burning 1200 ms regardless of how fast the server responds.
        try:
            self.page.wait_for_url(
                lambda u: "/student/login" not in u.lower(),
                timeout=15000,
                wait_until="domcontentloaded",
            )
        except Exception:
            # Timeout means we're still on the login page — proceed to error detection below.
            pass


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

    def _extract_student_name(self) -> str:
        """Extract student name from the Adamas LMS dashboard.

        The dashboard shows:
            Good Morning!          ← h2 / heading element
            DHEERAJ KUMAR          ← next sibling (yellow text, ALL CAPS)
            Registration No.: ...

        The name is a SEPARATE element right after the greeting, not
        part of the same text node — so simple "Good Morning, Name" regex fails.
        """
        import re as _re

        # ── Helpers ────────────────────────────────────────────────────────────
        def _clean(text: str) -> str:
            return " ".join(text.split()).strip()

        def _looks_like_name(text: str) -> bool:
            t = text.strip()
            # Must be 3–60 chars, only letters/spaces, at least 2 words preferred
            return bool(
                3 <= len(t) <= 60
                and _re.fullmatch(r"[A-Za-z][A-Za-z\s'\-]+", t)
                and not _re.fullmatch(r"(?i)(good\s+)?(morning|afternoon|evening)[!.,]?", t)
            )

        def _title(text: str) -> str:
            """Title-case — handles ALL CAPS names like DHEERAJ KUMAR."""
            return text.strip().title()

        # ── Strategy 1: next sibling of the greeting element ──────────────────
        # The greeting ("Good Morning!", "Good Afternoon!", "Good Evening!") is
        # one element; the student name is the very next sibling.
        greeting_variants = [
            "Good Morning!",
            "Good Afternoon!",
            "Good Evening!",
            "Good Morning",
            "Good Afternoon",
            "Good Evening",
        ]
        for greeting in greeting_variants:
            try:
                greeting_loc = self.page.locator(f"text={greeting}").first
                if not greeting_loc:
                    continue

                # Direct next sibling via XPath
                next_sib = greeting_loc.locator("xpath=following-sibling::*[1]")
                if next_sib.count() > 0:
                    text = _clean(next_sib.first.text_content() or "")
                    if _looks_like_name(text):
                        return _title(text)

                # One level up — parent's next sibling children
                parent_next = greeting_loc.locator("xpath=../following-sibling::*[1]")
                if parent_next.count() > 0:
                    text = _clean(parent_next.first.text_content() or "")
                    if _looks_like_name(text):
                        return _title(text)

                # Parent container — scan direct children for a name-like element
                parent = greeting_loc.locator("xpath=..")
                children = parent.locator("xpath=*")
                count = children.count()
                for i in range(1, min(count, 5)):   # skip index 0 (the greeting itself)
                    text = _clean(children.nth(i).text_content() or "")
                    if _looks_like_name(text):
                        return _title(text)
            except Exception:
                continue

        # ── Strategy 2: full page text with newline-aware regex ──────────────
        # When the greeting and name are in adjacent elements, they appear
        # on consecutive lines in text_content().
        try:
            body_text = self.page.locator("body").text_content() or ""
            pattern = _re.compile(
                r"Good\s+(?:Morning|Afternoon|Evening)[!.,]?\s*\n\s*([A-Z][A-Z\s'\-]{2,50})\s*\n",
                _re.MULTILINE,
            )
            m = pattern.search(body_text)
            if m:
                name = _clean(m.group(1))
                if _looks_like_name(name):
                    return _title(name)

            # Also try inline version (no newline) as a last resort
            inline_pattern = _re.compile(
                r"Good\s+(?:Morning|Afternoon|Evening)[!.,\s]+([A-Za-z][A-Za-z\s'\-]{2,50}?)(?:\s*[!.,]|\s+Registration|\s+AU/|\s*$)",
            )
            m2 = inline_pattern.search(body_text)
            if m2:
                name = _clean(m2.group(1))
                if _looks_like_name(name):
                    return _title(name)
        except Exception:
            pass

        # ── Strategy 3: topbar / navbar profile element ───────────────────────
        profile_selectors = [
            ".user-name",
            ".navbar .username",
            ".topbar .user-name",
            ".header-user-name",
            ".user-info .name",
            "[class*='student'][class*='name']",
        ]
        for sel in profile_selectors:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    text = _clean(loc.first.text_content() or "")
                    if _looks_like_name(text):
                        return _title(text)
            except Exception:
                continue

        return ""
