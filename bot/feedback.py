import re
import time
from html import unescape
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from .logger import logger
from .selectors import FeedbackDashboardSelectors, FeedbackFormSelectors
from .models import ProgressSummary
from .config import Config
from .utils import safe_click, save_error_artifacts, safe_locator_or

class FeedbackProcessor:
    def __init__(self, page: Page, config: Config, browser_manager: Optional[Any] = None):
        self.page = page
        self.config = config
        self.browser_manager = browser_manager
        self.summary = ProgressSummary()
        self.blocked_entries_by_subject = {}
        self.subject_targets: list[dict[str, Any]] = []
        
        # Cache for compiled regex patterns (memory optimization)
        self._parsed_urls_cache: dict = {}
        
    def _clear_subject_memory(self) -> None:
        """Clear subject-specific memory to reduce mid-run memory footprint.
        
        Safely clears browser session, blocked entries, and URL cache.
        All operations are exception-safe and non-critical.
        """
        # Clear browser session to free DOM memory (if browser_manager exists)
        if self.browser_manager is not None:
            try:
                # Verify that clear_session is callable before invoking
                if hasattr(self.browser_manager, 'clear_session') and callable(self.browser_manager.clear_session):
                    self.browser_manager.clear_session()
                else:
                    logger.debug("Browser manager does not have callable clear_session method")
            except Exception as e:
                logger.debug(f"Error clearing browser session (non-critical): {e}")
        
        # Clear blocked entries dict (always safe)
        try:
            self.blocked_entries_by_subject.clear()
        except Exception as e:
            logger.debug(f"Error clearing blocked entries: {e}")
        
        # Clear URL parsing cache (always safe)
        try:
            self._parsed_urls_cache.clear()
        except Exception as e:
            logger.debug(f"Error clearing URL cache: {e}")
        
        logger.debug("Cleared subject-specific memory cache")

    def process_all(self) -> ProgressSummary:
        logger.info("Detecting subjects with pending feedback...")

        try:
            self._wait_for_feedback_dashboard_ready()
        except PlaywrightTimeoutError:
            logger.info("No subjects found or feedback dashboard structure unrecognized.")
            return self.summary

        subject_locators = self._resolve_subject_locators()
        if subject_locators is None:
            logger.info("No subjects found.")
            return self.summary

        self.subject_targets = self._collect_subject_targets(subject_locators)

        # Last-resort fallback: preserve old behavior if aggressive filtering removed everything.
        if not self.subject_targets:
            raw_count = subject_locators.count()
            for i in range(raw_count):
                text = self._normalize_whitespace(subject_locators.nth(i).text_content() or "")
                self.subject_targets.append({
                    "raw_index": i,
                    "name": text or f"Subject {i + 1}",
                    "signature": f"idx:{i}",
                    "declared_pending": None,
                })

        subject_count = len(self.subject_targets)
        self.summary.total_subjects_found = subject_count

        if subject_count == 0:
            logger.info("No subjects found.")
            return self.summary

        logger.info(f"Found {subject_count} subjects to process.")

        for i, subject in enumerate(self.subject_targets):
            subject_name = subject["name"]

            if subject.get("declared_pending") == 0:
                logger.info(
                    f"--- Skipping Subject {i+1}/{subject_count}: {subject_name} (dashboard reports no pending entries) ---"
                )
                self._clear_subject_memory()
                continue

            logger.info(f"--- Processing Subject {i+1}/{subject_count}: {subject_name} ---")
            self._process_subject_by_index(i, subject_name)
            
            # Memory optimization: clear subject-specific state after processing
            self._clear_subject_memory()

        return self.summary

    def _process_subject_by_index(self, subject_index: int, subject_name: str):
        """Process a single subject by its index to avoid stale element issues."""
        try:
            self._open_subject_by_run_index(subject_index)

            declared_pending = self._get_declared_pending_for_subject(subject_index)
            pending_count, pending_item_count, disabled_count = self._scan_pending_state(wait_timeout_ms=3200)

            # Dashboard metadata says pending exists, but DOM has no actionable button yet.
            # Re-open once to recover from modal hydration race conditions in headless runs.
            if pending_count == 0 and (declared_pending or 0) > 0 and disabled_count == 0:
                logger.warning(
                    "Dashboard reports pending entries but no actionable button was detected. "
                    "Refreshing subject panel once."
                )
                self._return_to_subject_list()
                self._open_subject_by_run_index(subject_index)
                pending_count, pending_item_count, disabled_count = self._scan_pending_state(wait_timeout_ms=3200)

            self.summary.total_pending_found += pending_count
            logger.info(f"Pending entries found: {pending_count}")

            if pending_count == 0 and disabled_count > 0:
                logger.info("Pending entries exist but are currently unavailable due LMS time restrictions.")
            elif pending_count == 0 and (declared_pending or 0) > 0 and pending_item_count > 0:
                logger.warning(
                    "Pending rows are visible, but no clickable Give Feedback action is currently available."
                )
            elif pending_count == 0 and (declared_pending or 0) > 0:
                logger.warning(
                    "Dashboard shows pending entries, but subject details did not expose actionable rows."
                )

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

            current_count, pending_item_count, disabled_count = self._scan_pending_state(wait_timeout_ms=1400)

            if current_count == 0 and disabled_count > 0:
                logger.info("Remaining pending entries are currently unavailable (disabled by LMS window).")
                break

            if current_count == 0 and pending_item_count > 0:
                logger.info("Pending rows remain but no clickable feedback action is currently available.")
                break

            # If no more pending entries, we're done
            if current_count == 0:
                logger.info(f"No more pending entries. Processed {completed} items.")
                break

            available_count = self._count_unblocked_entries_for_subject(subject_index)
            if available_count == 0:
                logger.info("Remaining entries are already blocked/skipped for this subject.")
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
                logger.info("Subject completed: only already-submitted entries remain.")
                break


    def _submit_single_feedback(self, subject_index: int) -> bool:
        """Submit a single feedback form. Returns True on success."""
        button_signature = ""
        try:
            # Find and click the next unblocked "Give Feedback" button for this subject
            next_btn = self._get_next_unblocked_feedback_button(subject_index)
            if next_btn is None:
                logger.info("No unblocked feedback entries left for this subject.")
                return False

            give_feedback_btn, button_signature = next_btn
            before_click_url = self.page.url
            try:
                try:
                    give_feedback_btn.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass

                give_feedback_btn.click(timeout=7000)
            except PlaywrightTimeoutError:
                logger.warning("Pending entry became unavailable before click. Skipping this entry.")
                self.summary.total_skipped += 1
                self._block_subject_entry(subject_index, button_signature, "")
                return True
            except Exception as click_error:
                logger.warning(f"Give Feedback click failed for current entry. Skipping. reason={click_error}")
                self.summary.total_skipped += 1
                self._block_subject_entry(subject_index, button_signature, "")
                return True

            # Wait for page to react: URL change, toast, or modal update.
            # Resolves as soon as any change is detected (faster than a 700 ms fixed wall).
            try:
                self.page.wait_for_function(
                    """() => {
                        const toast = document.querySelector('#toast-container .toast');
                        return toast !== null;
                    }""",
                    timeout=500,
                )
            except Exception:
                # No toast within 500 ms — that's fine; proceed to URL check.
                pass

            # If LMS says this selected date has no classes, skip this date permanently
            if self._is_no_classes_for_selected_date_error():
                logger.info("[SKIPPED] No classes found for selected date. Skipping this date entry.")
                self.summary.total_skipped += 1
                self._block_subject_entry(subject_index, button_signature, "")
                return True

            # Wait for URL to change (resolves instantly rather than polling 120ms×25).
            try:
                self.page.wait_for_url(
                    lambda u: u != before_click_url,
                    timeout=3000,
                    wait_until="domcontentloaded",
                )
            except Exception:
                # URL didn't change within 3 s — modal or same-page flow; continue.
                pass


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
                FeedbackFormSelectors.SUBMIT_BTN_FALLBACK_3,
            ], wait_timeout_ms=6000, fallback_when_empty=False, warn_on_empty=False)

            if submit_btn is None or submit_btn.count() == 0:
                # Some entries remain on the modal dashboard when action is unavailable.
                if self.page.url == before_click_url:
                    logger.warning("Give Feedback click did not open a form. Skipping this entry for current run.")
                    self.summary.total_skipped += 1
                    self._block_subject_entry(subject_index, button_signature, "")
                    return True
                raise RuntimeError("Feedback form loaded but submit button was not found.")

            actionable_submit_btn = self._pick_actionable_locator(submit_btn)
            if actionable_submit_btn is None:
                if self.page.url == before_click_url:
                    logger.warning("Give Feedback flow stayed on dashboard without actionable submit. Skipping entry.")
                    self.summary.total_skipped += 1
                    self._block_subject_entry(subject_index, button_signature, "")
                    return True
                raise RuntimeError("Feedback form loaded but submit button is not actionable.")

            if self.config.dry_run:
                logger.info("[DRY RUN] Form loaded. Skipping actual submit.")
                self.summary.total_skipped += 1
                self._block_subject_entry(subject_index, button_signature, url_signature)
                self._skip_current_feedback_date()
                return True

            safe_click(actionable_submit_btn)

            # Wait for form to close and page to settle
            try:
                actionable_submit_btn.wait_for(state="hidden", timeout=20000)
            except Exception:
                logger.warning("Submit button never disappeared. Assuming success.")

            # Wait for DOM to update and new buttons to be ready.
            # domcontentloaded is sufficient and ~600 ms faster than a blind 1200 ms wall.
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            self.summary.total_submitted += 1
            logger.info("[SUCCESS] Feedback submitted.")
            return True

        except Exception as e:
            logger.error(f"Exception during form submission: {e}")
            save_error_artifacts(self.page, "submit_form_fail")
            if button_signature:
                self._block_subject_entry(subject_index, button_signature, "")
            return False

    def _get_next_unblocked_feedback_button(self, subject_index: int):
        """Return next Give Feedback button that is not blocked for this subject."""
        give_feedback_buttons = self._get_pending_feedback_buttons()
        if not give_feedback_buttons:
            return None

        blocked = self.blocked_entries_by_subject.get(subject_index, set())

        for i, btn in enumerate(give_feedback_buttons):
            signature = self._get_button_signature(btn, i)
            if signature and signature in blocked:
                continue
            return btn, signature

        # Every visible entry is blocked for this subject.
        return None

    def _count_unblocked_entries_for_subject(self, subject_index: int) -> int:
        """Count currently visible Give Feedback buttons that are not blocked for this subject."""
        give_feedback_buttons = self._get_pending_feedback_buttons()
        if not give_feedback_buttons:
            return 0

        blocked = self.blocked_entries_by_subject.get(subject_index, set())
        unblocked = 0

        for i, btn in enumerate(give_feedback_buttons):
            sig = self._get_button_signature(btn, i)
            if sig and sig in blocked:
                continue
            unblocked += 1

        return unblocked

    def _block_subject_entry(self, subject_index: int, button_signature: str, url_signature: str):
        """Store a skipped/already-submitted entry signature so it is never clicked again.
        
        Memory optimization: cap blocked set size at 100 entries per subject to prevent 
        quadratic memory growth in subjects with many feedback items.
        
        Bulletproof: handles edge cases with set operations and empty collections.
        """
        blocked = self.blocked_entries_by_subject.setdefault(subject_index, set())
        
        # If set is already large, remove oldest 25% before adding new entry
        MAX_BLOCKED_SIZE = 100
        if len(blocked) >= MAX_BLOCKED_SIZE:
            # Remove ~25% of oldest entries to make room
            remove_count = max(1, len(blocked) // 4)  # Ensure at least 1 removal
            removed = 0
            try:
                # Pop entries from set (order is not guaranteed but works for memory optimization)
                for _ in range(remove_count):
                    try:
                        blocked.pop()
                        removed += 1
                    except KeyError:
                        break  # Set is empty or no more entries
                
                if removed > 0:
                    logger.debug(f"Trimmed {removed} blocked entries for subject {subject_index} (now {len(blocked)} entries)")
            except Exception as e:
                logger.debug(f"Error trimming blocked entries: {e}")
        
        # Add new signatures (safe even if empty strings)
        if button_signature:
            try:
                blocked.add(button_signature)
            except Exception as e:
                logger.debug(f"Error adding button signature: {e}")
        
        if url_signature:
            try:
                blocked.add(url_signature)
            except Exception as e:
                logger.debug(f"Error adding URL signature: {e}")

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
        """Extract entry key from URL so the same date/period is never retried.
        
        Memory optimization: cache parsed URLs to avoid repeated URL parsing.
        """
        current_url = self.page.url
        
        # Check cache first
        if current_url in self._parsed_urls_cache:
            return self._parsed_urls_cache[current_url]
        
        result = ""
        try:
            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            attend_date = params.get("attendDate", [""])[0]
            period_id = params.get("periodId", [""])[0]
            if attend_date or period_id:
                result = f"url:attendDate={attend_date}|periodId={period_id}"
        except Exception:
            pass
        
        # Cache the result
        self._parsed_urls_cache[current_url] = result
        return result

    def _is_feedback_already_submitted(self) -> bool:
        """Check if the current page shows 'Feedback Already Submitted'."""
        try:
            return self._has_visible_match([
                FeedbackFormSelectors.ALREADY_SUBMITTED_BANNER,
                FeedbackFormSelectors.ALREADY_SUBMITTED_TEXT,
                FeedbackFormSelectors.ALREADY_SUBMITTED_TEXT_FALLBACK,
            ])
        except Exception as e:
            logger.debug(f"Could not check if feedback was already submitted: {e}")
            return False

    def _is_no_classes_for_selected_date_error(self) -> bool:
        """Check if LMS returned date-level feedback error after clicking Give Feedback."""
        try:
            # Give toast a brief moment to appear — 200 ms is enough for a DOM paint;
            # the old 400 ms sleep was twice as long as needed.
            self.page.wait_for_timeout(200)
            return self._has_visible_match([
                FeedbackFormSelectors.NO_CLASSES_FOR_DATE_ERROR,
                FeedbackFormSelectors.FEEDBACK_ERROR_TITLE,
            ])
        except Exception as e:
            logger.debug(f"Could not detect date-level feedback error: {e}")
            return False

    def _has_visible_match(self, selectors: Iterable[str], max_scan: int = 6) -> bool:
        """Return True if at least one selector resolves to a visible element."""
        for selector in selectors:
            try:
                loc = self.page.locator(selector)
                count = loc.count()
                if count == 0:
                    continue

                for i in range(min(count, max_scan)):
                    candidate = loc.nth(i)
                    if candidate.is_visible() or self._is_locator_rendered(candidate):
                        return True
            except Exception:
                continue

        return False

    def _skip_current_feedback_date(self):
        """Skip the current date entry and return to the subject feedback list."""
        try:
            if "/give-feedback/" in self.page.url.lower():
                # domcontentloaded is safe here; subsequent code polls DOM elements directly.
                self.page.go_back(wait_until="domcontentloaded", timeout=15000)
                self.page.wait_for_timeout(150)
                try:
                    self.page.wait_for_load_state("domcontentloaded", timeout=6000)
                except Exception:
                    pass
            else:
                self._close_subject_modal_if_open()
        except Exception as e:
            logger.warning(f"Failed to skip current date entry cleanly: {e}")
            raise

    def _ensure_subject_dates_page(self, subject_index: int):
        """Ensure we are inside the current subject's date list before counting pending entries."""
        try:
            if self._count_current_pending_buttons() > 0 or self._count_pending_feedback_items() > 0:
                return

            target = self._get_subject_target(subject_index)
            if target and target.get("declared_pending") == 0:
                return

            from .navigation import NavigationHandler
            nav = NavigationHandler(self.page)
            nav.go_to_feedback(force_reload=True)
            self._wait_for_feedback_dashboard_ready()
            self._open_subject_by_run_index(subject_index)
        except Exception as e:
            logger.warning(f"Failed to ensure subject dates page: {e}")
            raise

    def _return_to_subject_list(self):
        """Navigate back to the feedback subject list."""
        try:
            if self._close_subject_modal_if_open():
                self.page.wait_for_timeout(100)  # was 300 ms — 200 ms saved per subject

            subject_locators = self._resolve_subject_locators()
            if subject_locators is not None and subject_locators.count() > 0:
                return

            from .navigation import NavigationHandler
            nav = NavigationHandler(self.page)
            nav.go_to_feedback(force_reload=True)
            self.page.wait_for_timeout(250)  # was 600 ms — 350 ms saved per subject
        except Exception as e:
            logger.warning(f"Forced navigation failed. Attempting Escape key... {e}")
            try:
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(200)
            except Exception as e2:
                logger.warning(f"Escape key also failed: {e2}")

    def _wait_for_feedback_dashboard_ready(self):
        """Wait until feedback dashboard subject containers are available."""
        self.page.wait_for_load_state("domcontentloaded", timeout=20000)
        # Skip networkidle — LMS analytics hold it open for seconds. The polling
        # loop below already handles waiting for the actual subject DOM elements.

        deadline = time.time() + 12
        while time.time() < deadline:
            subject_locators = self._resolve_subject_locators()
            if subject_locators is not None and subject_locators.count() > 0:
                return

            self._expand_feedback_section_if_collapsed()
            self.page.wait_for_timeout(300)

        raise PlaywrightTimeoutError("Feedback subject containers did not appear.")

    def _expand_feedback_section_if_collapsed(self):
        """Open feedback accordion if dashboard content is collapsed."""
        try:
            feedback_content = self.page.locator("#feedbackContent")
            if feedback_content.count() == 0:
                return

            style = (feedback_content.first.get_attribute("style") or "").lower()
            if "display: none" not in style:
                return

            toggle = safe_locator_or(
                self.page,
                [
                    ".feedback-toggle-btn",
                    "#feedbackCollapseIcon",
                ],
                fallback_when_empty=False,
                warn_on_empty=False,
            )
            if toggle is not None and toggle.count() > 0:
                safe_click(toggle.first)
                self.page.wait_for_timeout(500)
        except Exception as e:
            logger.debug(f"Feedback collapse toggle check failed: {e}")

    def _resolve_subject_locators(self):
        """Return the first subject locator strategy that yields elements."""
        selectors = [
            FeedbackDashboardSelectors.SUBJECT_CARD_PRIMARY,
            FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_1,
            FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_2,
            FeedbackDashboardSelectors.SUBJECT_CARD_FALLBACK_3,
        ]

        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = locator.count()
                if count > 0:
                    logger.debug(f"Using subject selector '{selector}' ({count} matches).")
                    return locator
            except Exception as e:
                logger.debug(f"Subject selector '{selector}' failed: {e}")

        return None

    def _collect_subject_targets(self, subject_locators) -> list[dict[str, Any]]:
        """Extract stable, de-duplicated subject targets from current dashboard."""
        targets: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()

        count = subject_locators.count()
        for raw_index in range(count):
            loc = subject_locators.nth(raw_index)
            subject_name = self._extract_subject_name(loc)
            if not self._is_valid_subject_name(subject_name):
                logger.debug(f"Skipping non-subject candidate at index {raw_index}: '{subject_name}'")
                continue

            signature = self._build_subject_signature(loc, raw_index, subject_name)
            if signature in seen_signatures:
                logger.debug(f"Skipping duplicate subject candidate at index {raw_index}: '{subject_name}'")
                continue

            seen_signatures.add(signature)
            targets.append({
                "raw_index": raw_index,
                "name": subject_name,
                "signature": signature,
                "declared_pending": self._extract_declared_pending_count(loc),
            })

        return targets

    def _extract_subject_name(self, subject_locator) -> str:
        """Extract a clean subject name from a subject card/row element."""
        onclick_attr = ""
        try:
            onclick_attr = subject_locator.get_attribute("onclick") or ""
        except Exception:
            pass

        onclick_name = self._extract_subject_name_from_onclick(onclick_attr)
        if onclick_name:
            return onclick_name

        for selector in ["h6", "h5", "h4", ".subject-name", ".subject-title"]:
            try:
                name_loc = subject_locator.locator(selector)
                if name_loc.count() == 0:
                    continue
                candidate = self._normalize_whitespace(name_loc.first.text_content() or "")
                if candidate and self._is_valid_subject_name(candidate):
                    return candidate
            except Exception:
                continue

        try:
            raw_text = subject_locator.text_content() or ""
        except Exception:
            raw_text = ""

        lines = [self._normalize_whitespace(line) for line in raw_text.splitlines()]
        for line in lines:
            if not line:
                continue
            if "||" in line:
                line = self._normalize_whitespace(line.split("||", 1)[1])
            if self._is_valid_subject_name(line):
                return line

        compact = self._normalize_whitespace(raw_text)
        if "||" in compact:
            compact = self._normalize_whitespace(compact.split("||", 1)[1])
        if self._is_valid_subject_name(compact):
            return compact

        return ""

    def _extract_subject_name_from_onclick(self, onclick_attr: str) -> str:
        """Parse subject name from showSubjectFeedbackChart onclick handler."""
        if not onclick_attr:
            return ""

        decoded = unescape(onclick_attr)
        match = re.search(
            r"showSubjectFeedbackChart\(\s*'[^']*'\s*,\s*'([^']+)'",
            decoded,
        )
        if not match:
            return ""

        return self._normalize_whitespace(match.group(1).replace("\\'", "'"))

    def _extract_declared_pending_count(self, subject_locator) -> int | None:
        """Best-effort parse of pending entry count from onclick payload."""
        try:
            onclick_attr = subject_locator.get_attribute("onclick") or ""
        except Exception:
            return None

        if not onclick_attr:
            return None

        decoded = unescape(onclick_attr)
        compact = re.sub(r"\s+", "", decoded)

        if "showSubjectFeedbackChart" not in decoded:
            return None

        # Primary signal: dashboard payload includes one object per pending entry.
        payload_count = decoded.count("attendance_header_id")
        if payload_count > 0:
            return payload_count

        # ",[])" means the pending-entries array argument is empty.
        if ",[])" in compact or compact.endswith(",[])"):
            return 0

        # Fallback: infer pending as (classes attended - feedback already given)
        # from showSubjectFeedbackChart(subjectId, name, given, attended, percent, payload).
        stats_match = re.search(
            r"showSubjectFeedbackChart\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*(\d+)\s*,\s*(\d+)\s*,",
            decoded,
        )
        if stats_match:
            given_count = int(stats_match.group(1))
            attended_count = int(stats_match.group(2))
            return max(attended_count - given_count, 0)

        return None

    def _build_subject_signature(self, subject_locator, raw_index: int, subject_name: str) -> str:
        """Create a stable per-subject signature for de-duplication and diagnostics."""
        try:
            onclick_attr = subject_locator.get_attribute("onclick") or ""
        except Exception:
            onclick_attr = ""

        if onclick_attr:
            decoded = unescape(onclick_attr)
            id_match = re.search(r"showSubjectFeedbackChart\(\s*'([^']+)'", decoded)
            if id_match:
                return f"subject_id:{id_match.group(1)}"
            return f"onclick:{decoded}"

        for attr in ["data-subject-id", "data-course", "id"]:
            try:
                value = subject_locator.get_attribute(attr)
                if value:
                    return f"{attr}:{value}"
            except Exception:
                continue

        return f"idx:{raw_index}:{subject_name.lower()}"

    def _normalize_whitespace(self, value: str) -> str:
        return " ".join(value.split()).strip()

    def _looks_like_subject_code(self, text: str) -> bool:
        return bool(re.fullmatch(r"[A-Z]{2,}\d{2,}[A-Z0-9-]*", text.strip()))

    def _looks_like_non_subject_fragment(self, text: str) -> bool:
        stripped = text.strip()
        lowered = stripped.lower()

        if not stripped:
            return True
        if len(stripped) < 3:
            return True
        if lowered in {"completed", "pending", "unavailable", "feedback dashboard", "subject progress"}:
            return True
        if re.fullmatch(r"\d+(?:\.\d+)?%", stripped):
            return True
        if re.fullmatch(r"\d+\s*/\s*\d+", stripped):
            return True
        if re.fullmatch(r"subject\s+\d+", lowered):
            return True
        if self._looks_like_subject_code(stripped):
            return True

        return False

    def _is_valid_subject_name(self, name: str) -> bool:
        if self._looks_like_non_subject_fragment(name):
            return False
        return bool(re.search(r"[A-Za-z]", name))

    def _get_subject_target(self, run_index: int) -> dict[str, Any] | None:
        if run_index < 0 or run_index >= len(self.subject_targets):
            return None
        return self.subject_targets[run_index]

    def _get_declared_pending_for_subject(self, run_index: int) -> int | None:
        target = self._get_subject_target(run_index)
        if target is None:
            return None

        declared = target.get("declared_pending")
        if isinstance(declared, int) and declared >= 0:
            return declared

        return None

    def _open_subject_by_run_index(self, run_index: int):
        """Click the subject represented by run_index and wait for pending list state."""
        target = self._get_subject_target(run_index)
        if target is None:
            raise RuntimeError(f"Unknown subject index: {run_index}")

        subject_locators = self._resolve_subject_locators()
        if subject_locators is None:
            raise RuntimeError("Subject cards are not available on dashboard.")

        raw_index = int(target["raw_index"])
        if raw_index >= subject_locators.count():
            raise RuntimeError(
                f"Subject index out of range while opening subject: raw_index={raw_index}"
            )

        safe_click(subject_locators.nth(raw_index))
        self._wait_for_subject_panel()

    def _wait_for_subject_panel(self):
        """Wait until modal/list/form state appears after subject click."""
        # Phase 1: wait for the modal itself to open (Bootstrap adds .show / .in).
        deadline = time.time() + 12
        modal_opened = False
        while time.time() < deadline:
            lowered_url = self.page.url.lower()
            if "/give-feedback/" in lowered_url:
                return

            # Modal is open when it carries the Bootstrap .show or .in class.
            if self.page.locator(
                "#subjectFeedbackModal.show, #subjectFeedbackModal.in"
            ).count() > 0:
                modal_opened = True
                break

            # Some LMS builds navigate directly without a modal.
            if self._has_visible_match([
                FeedbackDashboardSelectors.NO_PENDING_FEEDBACK_TEXT,
            ]):
                return

            self.page.wait_for_timeout(200)

        if not modal_opened:
            # Fall back: accept any panel-like state before giving up.
            if self._count_current_pending_buttons() > 0:
                return
            if self._count_pending_feedback_items() > 0:
                return
            if self._count_disabled_pending_buttons() > 0:
                return
            return  # timed out but proceed anyway

        # Phase 2: modal is open – wait for the AJAX call that populates
        # #pendingFeedbackList to settle.  Disabled buttons may already be
        # painted while enabled ones are still loading, so we must NOT bail out
        # as soon as we see disabled buttons; give the list time to fully load.
        ajax_deadline = time.time() + 6
        while time.time() < ajax_deadline:
            if "/give-feedback/" in self.page.url.lower():
                return
            if self._count_current_pending_buttons() > 0:
                return  # found enabled buttons – done
            if self._count_pending_feedback_items() > 0:
                return  # pending rows rendered; action buttons may still be state-dependent
            self.page.wait_for_timeout(250)

        # After the AJAX window, accept whatever state we have.
        return

    def _get_pending_feedback_buttons(self):
        """Return rendered and enabled Give Feedback buttons in current subject context."""
        selectors = [
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_2,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_3,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_BTN_FALLBACK_4,
        ]

        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = locator.count()
                if count == 0:
                    continue

                actionable = []
                for i in range(count):
                    candidate = locator.nth(i)
                    if self._is_locator_actionable(candidate):
                        actionable.append(candidate)

                if actionable:
                    return actionable
            except Exception:
                continue

        return []

    def _count_current_pending_buttons(self) -> int:
        buttons = self._get_pending_feedback_buttons()
        return len(buttons)

    def _count_pending_feedback_items(self) -> int:
        """Count pending rows rendered in the current subject panel, regardless of button state."""
        selectors = [
            FeedbackDashboardSelectors.PENDING_FEEDBACK_ITEM,
            FeedbackDashboardSelectors.PENDING_FEEDBACK_ITEM_FALLBACK,
            FeedbackDashboardSelectors.PENDING_FEEDBACK_ITEM_FALLBACK_2,
        ]

        best_count = 0
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = locator.count()
                if count == 0:
                    continue

                rendered = 0
                for i in range(count):
                    if self._is_locator_rendered(locator.nth(i)):
                        rendered += 1

                if rendered > best_count:
                    best_count = rendered
            except Exception:
                continue

        return best_count

    def _scan_pending_state(self, wait_timeout_ms: int = 0) -> tuple[int, int, int]:
        """Return (enabled_buttons, pending_rows, disabled_buttons), with optional short polling."""
        deadline = time.time() + (wait_timeout_ms / 1000.0) if wait_timeout_ms > 0 else None
        best_enabled = 0
        best_rows = 0
        best_disabled = 0

        while True:
            enabled = self._count_current_pending_buttons()
            rows = self._count_pending_feedback_items()
            disabled = self._count_disabled_pending_buttons()

            if enabled > best_enabled:
                best_enabled = enabled
            if rows > best_rows:
                best_rows = rows
            if disabled > best_disabled:
                best_disabled = disabled

            if enabled > 0:
                return enabled, max(rows, enabled), disabled

            if deadline is None or time.time() >= deadline:
                return best_enabled, best_rows, best_disabled

            self.page.wait_for_timeout(150)  # was 220 ms — faster scan polling

    def _count_disabled_pending_buttons(self) -> int:
        selectors = [
            FeedbackDashboardSelectors.GIVE_FEEDBACK_DISABLED_BTN,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_DISABLED_BTN_FALLBACK,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_DISABLED_BTN_FALLBACK_2,
            FeedbackDashboardSelectors.GIVE_FEEDBACK_DISABLED_BTN_FALLBACK_3,
        ]

        best_count = 0
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = locator.count()
                if count == 0:
                    continue

                rendered = 0
                for i in range(count):
                    if self._is_locator_rendered(locator.nth(i)):
                        rendered += 1

                if rendered > best_count:
                    best_count = rendered
            except Exception:
                continue

        return best_count

    def _is_locator_rendered(self, locator) -> bool:
        """Best-effort rendered check that tolerates headless/headful style-transition lag."""
        try:
            return bool(locator.evaluate(
                """(el) => {
                    if (!el || !el.isConnected) {
                        return false;
                    }
                    const style = window.getComputedStyle(el);
                    if (!style || style.display === 'none' || style.visibility === 'hidden') {
                        return false;
                    }
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }"""
            ))
        except Exception:
            return False

    def _is_locator_actionable(self, locator) -> bool:
        """Check whether a button is rendered and can receive pointer interaction."""
        try:
            if not locator.is_enabled():
                return False
        except Exception:
            return False

        if not self._is_locator_rendered(locator):
            return False

        try:
            blocks_pointer = bool(locator.evaluate(
                """(el) => {
                    const style = window.getComputedStyle(el);
                    return !!style && style.pointerEvents === 'none';
                }"""
            ))
            if blocks_pointer:
                return False
        except Exception:
            pass

        return True

    def _pick_actionable_locator(self, locators, max_scan: int = 10):
        """Return first actionable locator from a locator group."""
        if locators is None:
            return None

        try:
            count = locators.count()
        except Exception:
            return None

        for i in range(min(count, max_scan)):
            candidate = locators.nth(i)
            if self._is_locator_actionable(candidate):
                return candidate

        return None

    def _close_subject_modal_if_open(self) -> bool:
        """Close subject feedback modal if it is currently open."""
        try:
            modal_open = self.page.locator(FeedbackDashboardSelectors.SUBJECT_FEEDBACK_MODAL_OPEN)
            if modal_open.count() == 0:
                return False

            close_btn = safe_locator_or(
                self.page,
                [
                    f"{FeedbackDashboardSelectors.SUBJECT_FEEDBACK_MODAL} button[data-dismiss='modal']",
                    f"{FeedbackDashboardSelectors.SUBJECT_FEEDBACK_MODAL} button.close",
                ],
                fallback_when_empty=False,
                warn_on_empty=False,
            )
            if close_btn is not None and close_btn.count() > 0:
                safe_click(close_btn.first)
            else:
                self.page.keyboard.press("Escape")

            self.page.wait_for_timeout(400)
            return True
        except Exception:
            return False
