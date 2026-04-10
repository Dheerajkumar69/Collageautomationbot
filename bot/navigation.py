from playwright.sync_api import Page
from .logger import logger
from .selectors import SidebarSelectors
from .utils import save_error_artifacts, with_retry, safe_click, safe_locator_or

class NavigationHandler:
    def __init__(self, page: Page):
        self.page = page

    @with_retry(max_retries=3, delay=1.0)
    def go_to_feedback(self, force_reload: bool = False):
        logger.info("Navigating to Feedback section...")
        try:
            # If force_reload is requested, yield to the event loop briefly
            # so any in-flight navigation settles before we touch the DOM.
            if force_reload:
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)

            # If feedback section is already rendered on dashboard, no extra click is needed.
            if self.page.locator(SidebarSelectors.FEEDBACK_DASHBOARD_TITLE).count() > 0:
                logger.debug("Feedback dashboard already visible.")
                return

            # Use safe_locator_or for multiple selector fallbacks
            feedback_link = safe_locator_or(self.page, [
                SidebarSelectors.FEEDBACK_LINK,
                SidebarSelectors.FEEDBACK_LINK_FALLBACK_1,
                SidebarSelectors.FEEDBACK_LINK_FALLBACK_2,
                SidebarSelectors.FEEDBACK_LINK_FALLBACK_3,
            ], wait_timeout_ms=25000)

            if feedback_link is None:
                raise RuntimeError("Feedback navigation link was not found.")
            
            # Wait and click
            feedback_link.first.wait_for(state="visible", timeout=15000)
            safe_click(feedback_link.first)

            # In some layouts first click only expands the menu; click direct link if available.
            direct_feedback_link = self.page.locator(SidebarSelectors.FEEDBACK_LINK)
            if direct_feedback_link.count() > 0 and "academicfeedback" not in self.page.url.lower():
                safe_click(direct_feedback_link.first)
            
            # Use domcontentloaded — networkidle on LMS can block 2–6 s due to ads/analytics.
            self.page.wait_for_load_state("domcontentloaded", timeout=20000)
            logger.debug("Arrived at Feedback Dashboard.")
        except Exception as e:
            logger.error(f"Failed to navigate to Feedback: {e}")
            save_error_artifacts(self.page, "nav_feedback_failure")
            raise e
