from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from .config import Config
from .logger import logger

class BrowserManager:
    def __init__(self, config: Config):
        self.config = config
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None

    def start(self) -> Page:
        logger.info("Initializing Playwright browser...")
        self.playwright = sync_playwright().start()
        
        self.browser = self.playwright.chromium.launch(
            headless=self.config.headless,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        
        self.context = self.browser.new_context(
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.config.timeout_ms)
        self.page.set_default_navigation_timeout(self.config.navigation_timeout_ms)
        
        return self.page

    def close(self):
        logger.info("Cleaning up browser context...")
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
