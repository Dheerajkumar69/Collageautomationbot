from playwright.sync_api import Page
from .logger import logger
from .selectors import SidebarSelectors
from .utils import save_error_artifacts, with_retry, safe_click, safe_locator_or

class NavigationHandler:
    def __init__(self, page: Page):
        self.page = page

    @with_retry(max_retries=3, delay=2.0)
    def go_to_feedback(self, force_reload=False):
        logger.info("Navigating to Feedback section...")
        try:
            # Use safe_locator_or for multiple selector fallbacks
            feedback_link = safe_locator_or(self.page, [
                SidebarSelectors.FEEDBACK_LINK,
                SidebarSelectors.FEEDBACK_LINK_FALLBACK_1,
                SidebarSelectors.FEEDBACK_LINK_FALLBACK_2
            ])
            
            # Wait and click
            feedback_link.first.wait_for(state="visible", timeout=15000)
            safe_click(feedback_link.first)
            
            # Await dynamic DOM reconstruction
            self.page.wait_for_load_state("networkidle", timeout=20000)
            logger.debug("Arrived at Feedback Dashboard.")
        except Exception as e:
            logger.error(f"Failed to navigate to Feedback: {e}")
            save_error_artifacts(self.page, "nav_feedback_failure")
            raise e
