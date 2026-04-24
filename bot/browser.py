import fcntl
import os
import subprocess
import sys
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from .config import Config
from .logger import logger


class BrowserManager:
    def __init__(self, config: Config):
        self.config = config
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    @staticmethod
    def _is_missing_browser_error(exc: Exception) -> bool:
        msg = str(exc)
        return (
            "Executable doesn't exist" in msg
            or "Please run the following command to download new browsers" in msg
        )

    @staticmethod
    def _install_chromium(headless: bool) -> None:
        logger.warning("Chromium binary missing. Attempting Playwright install...")

        lock_path = "/tmp/collageauto_playwright_install.lock"

        # Guard install across concurrent processes.
        lock_file = open(lock_path, "w", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            cmd = [sys.executable, "-m", "playwright", "install"]
            if headless:
                # Headless shell is smaller and faster to download for server workloads.
                # Correct syntax: playwright install chromium --only-shell
                cmd.extend(["chromium", "--only-shell"])
            else:
                cmd.append("chromium")

            result = subprocess.run(
                cmd,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

        if result.returncode != 0:
            stdout_tail = (result.stdout or "").strip()[-1200:]
            stderr_tail = (result.stderr or "").strip()[-1200:]
            raise RuntimeError(
                "Playwright chromium install failed. "
                f"exit_code={result.returncode} stdout_tail={stdout_tail!r} stderr_tail={stderr_tail!r}"
            )

        logger.info("Playwright chromium install completed.")

    def _launch_browser(self) -> Browser:
        if self.playwright is None:
            raise RuntimeError("Playwright is not initialized")

        extra_args = [
            "--disable-blink-features=AutomationControlled",
            "--window-size=1920,1080",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",                   # required on Render's headless Linux
            "--disable-software-rasterizer",   # prevent GPU fallback that hangs
        ]

        if self.config.headless:
            # Speed-up flags: skip image decoding & unnecessary features in headless runs.
            extra_args += [
                "--blink-settings=imagesEnabled=false",
                "--disable-background-networking",
                "--disable-client-side-phishing-detection",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-hang-monitor",
                "--disable-popup-blocking",
                "--disable-prompt-on-repost",
                "--disable-sync",
                "--disable-translate",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run",
                "--safebrowsing-disable-auto-update",
            ]

        return self.playwright.chromium.launch(
            headless=self.config.headless,
            args=extra_args,
        )

    # Resource types that serve zero purpose in a headless automation run.
    # NOTE: Do NOT block 'websocket' — Playwright sync API cannot safely abort
    # websocket upgrades and will raise an error on some LMS builds.
    _BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

    # Known tracking / analytics hostnames that add network latency for nothing.
    # NOTE: Do NOT block cdn.jsdelivr.net — many Bootstrap/jQuery LMS sites load
    # critical JS (modals, dropdowns) from there; blocking it kills functionality.
    _BLOCKED_RESOURCE_HOSTS = {
        "google-analytics.com",
        "googletagmanager.com",
        "doubleclick.net",
        "facebook.net",
        "hotjar.com",
        "clarity.ms",
    }

    def _setup_resource_blocking(self) -> None:
        """Abort resource requests that automation never needs (headless only)."""
        if not self.config.headless or self.context is None:
            return

        def _route_handler(route, request):
            resource_type = request.resource_type
            if resource_type in self._BLOCKED_RESOURCE_TYPES:
                route.abort()
                return
            # Block known tracking/analytics hosts by substring match.
            url = request.url
            for blocked_host in self._BLOCKED_RESOURCE_HOSTS:
                if blocked_host in url:
                    route.abort()
                    return
            route.continue_()

        self.context.route("**/*", _route_handler)

    def start(self) -> Page:
        logger.info("Initializing Playwright browser...")
        self.playwright = sync_playwright().start()

        try:
            self.browser = self._launch_browser()
        except Exception as exc:
            if not self._is_missing_browser_error(exc):
                raise

            logger.warning("Playwright browser not found at runtime, running one-time install.")
            if self.playwright:
                self.playwright.stop()

            self._install_chromium(self.config.headless)
            self.playwright = sync_playwright().start()
            self.browser = self._launch_browser()

        if self.config.headless:
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                screen={"width": 1920, "height": 1080},
                timezone_id=self.config.timezone_id,
            )
        else:
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                no_viewport=True,
                timezone_id=self.config.timezone_id,
            )

        # Block heavyweight resources in headless mode before the first page load.
        self._setup_resource_blocking()

        self.page = self.context.new_page()
        self.page.set_default_timeout(self.config.timeout_ms)
        self.page.set_default_navigation_timeout(self.config.navigation_timeout_ms)
        
        return self.page

    def clear_session(self) -> None:
        """Clear cookies and browser storage between subjects to reduce memory footprint.
        
        Safely handles cases where context/page may not be fully initialized.
        All operations are exception-safe to prevent cascade failures.
        """
        # Safety checks: ensure context and page exist
        if not hasattr(self, 'context') or self.context is None:
            logger.debug("Cannot clear session: context not initialized")
            return
        
        if not hasattr(self, 'page') or self.page is None:
            logger.debug("Cannot clear session: page not initialized")
            return
        
        # Clear cookies - single operation, atomic
        try:
            self.context.clear_cookies()
            logger.debug("Cleared browser cookies")
        except Exception as e:
            logger.debug(f"Error clearing cookies (non-critical): {e}")
        
        # Clear session/local storage - safe JavaScript execution with fallbacks
        try:
            self.page.evaluate("""
                () => {
                    try { sessionStorage.clear(); } catch (e) {}
                    try { localStorage.clear(); } catch (e) {}
                    return true;
                }
            """)
            logger.debug("Cleared browser storage")
        except Exception as e:
            logger.debug(f"Error clearing storage (non-critical): {e}")

    def close(self):
        logger.info("Cleaning up browser context...")
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
