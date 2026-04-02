import time
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from .logger import logger
from .selectors import FeedbackDashboardSelectors, FeedbackFormSelectors
from .models import ProgressSummary
from .config import Config
from .utils import safe_click, save_error_artifacts, safe_locator_or

class FeedbackProcessor:
    def __init__(self, page: Page, config: Config):
        self.page = page
        self.config = config
        self.summary = ProgressSummary()
        self.blocked_entries_by_subject = {}

    def process_all(self) -> ProgressSummary:
        logger.info("Detecting subjects with pending feedback...")
        
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
            
            # Try multiple subject selectors
            subject_locators = safe_locator_or(self.page, [
                FeedbackDashboardSelectors.SUBJECT_CARD_PRIMARY,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_1,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_2,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_3,
            ])
            
            # Wait for elements to attach
            try:
                subject_locators.first.wait_for(state="visible", timeout=10000)
            except PlaywrightTimeoutError:
                pass
                
        except PlaywrightTimeoutError:
            logger.info("No subjects found or feedback dashboard structure unrecognized.")
            return self.summary

        # To avoid Stale Element Reference, extract subject names first
        subject_count = subject_locators.count()
        self.summary.total_subjects_found = subject_count
        
        if subject_count == 0:
            logger.info("No subjects found.")
            return self.summary
            
        subject_names = []
        for i in range(subject_count):
            try:
                text = subject_locators.nth(i).text_content()
                subject_names.append(text.strip() if text else f"Subject {i+1}")
            except Exception as e:
                logger.debug(f"Could not extract name for subject {i}: {e}")
                subject_names.append(f"Subject {i+1}")
            
        logger.info(f"Found {subject_count} subjects to process.")

        for i, subject_name in enumerate(subject_names):
            logger.info(f"--- Processing Subject {i+1}/{subject_count}: {subject_name} ---")
            self._process_subject_by_index(i, subject_name)
            
        return self.summary

    def _process_subject_by_index(self, subject_index: int, subject_name: str):
        """Process a single subject by its index to avoid stale element issues."""
        try:
            # Re-fetch subject locators fresh to avoid stale references
            subject_locators = safe_locator_or(self.page, [
                FeedbackDashboardSelectors.SUBJECT_CARD_PRIMARY,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_1,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_2,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_3,
            ])
            
            subject_locator = subject_locators.nth(subject_index)
            safe_click(subject_locator)
            
            # Wait for either buttons or some text indicating there are no pending feedbacks
            time.sleep(2)  # Give animations time
            
            # Count pending feedback buttons
            give_feedback_buttons = safe_locator_or(self.page, [
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN,
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK,
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_2,
            ])
            
            pending_count = give_feedback_buttons.count()
            self.summary.total_pending_found += pending_count
            logger.info(f"Pending entries found: {pending_count}")
            
            if pending_count == 0:
                logger.info("No pending feedback for this subject.")
                self._return_to_subject_list()
                return

            # Register dialog handler once per subject
            self.page.once("dialog", lambda dialog: dialog.accept())
            
            self._process_pending_feedbacks_sequentially(pending_count, subject_index)
            self._return_to_subject_list()
            
        except Exception as e:
            logger.error(f"Failed to process subject '{subject_name}': {e}")
            self.summary.total_failed += 1
            save_error_artifacts(self.page, f"subject_fail_idx_{subject_index}")
            self._return_to_subject_list()

    def _process_pending_feedbacks_sequentially(self, initial_count: int, subject_index: int):
        """Process pending feedbacks one by one, safely recovering from stale elements."""
        completed = 0
        max_no_progress_attempts = max(initial_count * 3, 10)
        no_progress_attempts = 0
        previous_count = None

        while True:
            self._ensure_subject_dates_page(subject_index)
            
            # CRITICAL: Wait for page to stabilize before checking for buttons
            time.sleep(1)
            self.page.wait_for_load_state("networkidle", timeout=10000)
            
            # Re-fetch button count each iteration to detect DOM changes
            give_feedback_btn_loc = safe_locator_or(self.page, [
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN,
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK,
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_2,
            ])
            
            current_count = give_feedback_btn_loc.count()
            
            # If no more pending entries, we're done
            if current_count == 0:
                logger.info(f"✅ No more pending entries. Processed {completed} items.")
                break

            available_count = self._count_unblocked_entries_for_subject(subject_index)
            if available_count == 0:
                logger.info("✅ Remaining entries are already blocked/skipped for this subject.")
                break

            if previous_count is not None and current_count >= previous_count:
                no_progress_attempts += 1
            else:
                no_progress_attempts = 0

            if no_progress_attempts >= max_no_progress_attempts:
                logger.warning(
                    "No progress while processing pending feedback entries. "
                    f"Stopping this subject after {no_progress_attempts} attempts with {current_count} still visible."
                )
                break

            previous_count = current_count
            
            logger.info(f"Processing entry {completed + 1}/{initial_count}... ({current_count} pending remaining)")
            
            # Try to submit - this handles submitted/skipped/failed internally
            success = self._submit_single_feedback(subject_index)
            
            if success:
                completed += 1
                continue

            if self._count_unblocked_entries_for_subject(subject_index) == 0:
                logger.info("✅ Subject completed: only already-submitted entries remain.")
                break


    def _submit_single_feedback(self, subject_index: int) -> bool:
        """Submit a single feedback form. Returns True on success."""
        try:
            # Find and click the next unblocked "Give Feedback" button for this subject
            next_btn = self._get_next_unblocked_feedback_button(subject_index)
            if next_btn is None:
                logger.info("No unblocked feedback entries left for this subject.")
                return False

            give_feedback_btn, button_signature = next_btn
            safe_click(give_feedback_btn)
            
            # Wait for page to transition to form
            time.sleep(1)

            # If LMS says this selected date has no classes, skip this date permanently
            if self._is_no_classes_for_selected_date_error():
                logger.info("[SKIPPED] No classes found for selected date. Skipping this date entry.")
                self.summary.total_skipped += 1
                self._block_subject_entry(subject_index, button_signature, "")
                return True

            url_signature = self._extract_entry_signature_from_url()
            
            # CRITICAL: Check if feedback was already submitted before trying to submit
            if self._is_feedback_already_submitted():
                logger.info("[SKIPPED] Feedback already submitted for this entry.")
                self.summary.total_skipped += 1
                self._block_subject_entry(subject_index, button_signature, url_signature)
                self._skip_current_feedback_date()
                return True
            
            # Wait strongly for the submit button to ensure the form fully renders
            submit_btn = safe_locator_or(self.page, [
                FeedbackFormSelectors.SUBMIT_BTN,
                FeedbackFormSelectors.SUBMIT_BTN_FALLBACK,
                FeedbackFormSelectors.SUBMIT_BTN_FALLBACK_2,
            ])
            
            submit_btn.first.wait_for(state="visible", timeout=15000)
            
            if self.config.dry_run:
                logger.info("[DRY RUN] Form loaded. Skipping actual submit.")
                self.summary.total_skipped += 1
                self.page.go_back()
                time.sleep(2)  # Extended wait for page to recover
                return True
                
            safe_click(submit_btn.first)
            
            # Wait for form to close and page to settle
            try:
                submit_btn.first.wait_for(state="hidden", timeout=20000)
            except Exception:
                logger.warning("Submit button never disappeared. Assuming success.")
            
            # Critical: Wait for page to fully load and buttons to reset
            time.sleep(2)
            self.page.wait_for_load_state("networkidle", timeout=10000)
            self.summary.total_submitted += 1
            logger.info("[SUCCESS] Feedback submitted.")
            return True
            
        except Exception as e:
            logger.error(f"Exception during form submission: {e}")
            save_error_artifacts(self.page, "submit_form_fail")
            return False

    def _get_next_unblocked_feedback_button(self, subject_index: int):
        """Return next Give Feedback button that is not blocked for this subject."""
        give_feedback_btn = safe_locator_or(self.page, [
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_2,
        ])

        count = give_feedback_btn.count()
        blocked = self.blocked_entries_by_subject.get(subject_index, set())

        for i in range(count):
            btn = give_feedback_btn.nth(i)
            signature = self._get_button_signature(btn, i)
            if signature and signature in blocked:
                continue
            return btn, signature

        # Every visible entry is blocked for this subject.
        return None

    def _count_unblocked_entries_for_subject(self, subject_index: int) -> int:
        """Count currently visible Give Feedback buttons that are not blocked for this subject."""
        give_feedback_btn = safe_locator_or(self.page, [
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_2,
        ])

        count = give_feedback_btn.count()
        blocked = self.blocked_entries_by_subject.get(subject_index, set())
        unblocked = 0

        for i in range(count):
            sig = self._get_button_signature(give_feedback_btn.nth(i), i)
            if sig and sig in blocked:
                continue
            unblocked += 1

        return unblocked

    def _block_subject_entry(self, subject_index: int, button_signature: str, url_signature: str):
        """Store a skipped/already-submitted entry signature so it is never clicked again."""
        blocked = self.blocked_entries_by_subject.setdefault(subject_index, set())
        if button_signature:
            blocked.add(button_signature)
        if url_signature:
            blocked.add(url_signature)

    def _get_button_signature(self, button_locator, index: int = None) -> str:
        """Build a stable signature for a Give Feedback button from its attributes."""
        attr_names = ["href", "data-url", "onclick", "data-target", "id"]
        for attr in attr_names:
            try:
                value = button_locator.get_attribute(attr)
                if value:
                    return f"{attr}:{value.strip()}"
            except Exception:
                continue

        # Fallback: derive signature from nearest row/container text (typically includes date)
        try:
            container = button_locator.locator("xpath=ancestor::*[self::li or self::tr or self::div][1]")
            text = container.first.inner_text().strip()
            if text:
                compact = " ".join(text.split())
                return f"text:{compact[:180]}"
        except Exception:
            pass

        if index is not None:
            return f"idx:{index}"

        return ""

    def _extract_entry_signature_from_url(self) -> str:
        """Extract entry key from URL so the same date/period is never retried."""
        try:
            parsed = urlparse(self.page.url)
            params = parse_qs(parsed.query)
            attend_date = params.get("attendDate", [""])[0]
            period_id = params.get("periodId", [""])[0]
            if attend_date or period_id:
                return f"url:attendDate={attend_date}|periodId={period_id}"
        except Exception:
            pass
        return ""

    def _is_feedback_already_submitted(self) -> bool:
        """Check if the current page shows 'Feedback Already Submitted'."""
        try:
            # Check for already submitted banner or message
            already_submitted = safe_locator_or(self.page, [
                FeedbackFormSelectors.ALREADY_SUBMITTED_BANNER,
                FeedbackFormSelectors.ALREADY_SUBMITTED_TEXT,
            ])
            
            # If any element with these selectors is visible, feedback was already submitted
            return already_submitted.count() > 0
        except Exception as e:
            logger.debug(f"Could not check if feedback was already submitted: {e}")
            return False

    def _is_no_classes_for_selected_date_error(self) -> bool:
        """Check if LMS returned date-level feedback error after clicking Give Feedback."""
        try:
            error_toast = safe_locator_or(self.page, [
                FeedbackFormSelectors.NO_CLASSES_FOR_DATE_ERROR,
                FeedbackFormSelectors.FEEDBACK_ERROR_TITLE,
            ])
            return error_toast.count() > 0
        except Exception as e:
            logger.debug(f"Could not detect date-level feedback error: {e}")
            return False

    def _skip_current_feedback_date(self):
        """Skip the current date entry and return to the subject feedback list."""
        try:
            self.page.go_back(wait_until="networkidle", timeout=15000)
            time.sleep(1)
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.warning(f"Failed to skip current date entry cleanly: {e}")
            raise

    def _ensure_subject_dates_page(self, subject_index: int):
        """Ensure we are inside the current subject's date list before counting pending entries."""
        try:
            give_feedback_buttons = safe_locator_or(self.page, [
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN,
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK,
                FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_2,
            ])

            if give_feedback_buttons.count() > 0:
                return

            from .navigation import NavigationHandler
            nav = NavigationHandler(self.page)
            nav.go_to_feedback(force_reload=True)

            subject_locators = safe_locator_or(self.page, [
                FeedbackDashboardSelectors.SUBJECT_CARD_PRIMARY,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_1,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_2,
                FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_3,
            ])

            if subject_index >= subject_locators.count():
                raise RuntimeError(f"Subject index out of range while re-entering subject: {subject_index}")

            safe_click(subject_locators.nth(subject_index))
            time.sleep(2)
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.warning(f"Failed to ensure subject dates page: {e}")
            raise

    def _return_to_subject_list(self):
        """Navigate back to the feedback subject list."""
        try:
            from .navigation import NavigationHandler
            nav = NavigationHandler(self.page)
            nav.go_to_feedback(force_reload=True)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Forced navigation failed. Attempting Escape key... {e}")
            try:
                self.page.keyboard.press("Escape")
                time.sleep(1)
            except Exception as e2:
                logger.warning(f"Escape key also failed: {e2}")
