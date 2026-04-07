import time
import functools
from pathlib import Path
from typing import Callable, ParamSpec, Sequence, TypeVar
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError
from .logger import logger

P = ParamSpec("P")
R = TypeVar("R")

def safe_locator_or(
    page: Page,
    selectors_list: Sequence[str],
    wait_timeout_ms: int = 0,
    poll_interval_ms: int = 300,
) -> Locator | None:
    """
    Try multiple selectors in order, returning the first one that finds elements.
    
    Example:
        loc = safe_locator_or(page, [
            'button:has-text("Login")',
            'button[type="submit"]',
            'input[type="button"]'
        ])
    """
    if not selectors_list:
        return None

    deadline = time.time() + (wait_timeout_ms / 1000.0) if wait_timeout_ms > 0 else None
    poll_interval_ms = max(50, int(poll_interval_ms))

    while True:
        # Try each selector in order, return first visible match, then attached match.
        for selector in selectors_list:
            try:
                locator = page.locator(selector)

                visible_locator = locator.locator(":visible")
                if visible_locator.count() > 0:
                    logger.debug(f"✓ Visible selector matched: {selector[:60]}...")
                    return visible_locator

                if locator.count() > 0:
                    logger.debug(f"✓ Selector matched (non-visible): {selector[:60]}...")
                    return locator
            except Exception as e:
                logger.debug(f"✗ Selector failed: {selector[:60]}... ({str(e)[:30]})")
                continue

        if deadline is None or time.time() >= deadline:
            break

        page.wait_for_timeout(poll_interval_ms)
    
    # If no selector found elements, return the first one anyway (will fail gracefully)
    logger.warning(f"No selector matched any elements. Using first selector as fallback.")
    return page.locator(selectors_list[0])

def with_retry(max_retries: int = 3, delay: float = 2.0):
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_error: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    logger.debug(f"Attempt {attempt + 1} failed for {func.__name__}: {str(e)}")
                    time.sleep(delay)
            logger.error(f"Function {func.__name__} failed after {max_retries} attempts.")
            if last_error is None:
                raise RuntimeError(f"Function {func.__name__} failed without an exception.")
            raise last_error
        return wrapper
    return decorator

def save_error_artifacts(page: Page, step_name: str):
    """Saves HTML and a screenshot when something fails."""
    try:
        Path("errors").mkdir(exist_ok=True)
        timestamp = int(time.time())
        screenshot_path = f"errors/error_{step_name}_{timestamp}.png"
        html_path = f"errors/error_{step_name}_{timestamp}.html"
        
        page.screenshot(path=screenshot_path, full_page=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
            
        logger.info(f"Artifacts saved: {screenshot_path}")
        logger.info(f"Current URL: {page.url}")
    except Exception as e:
        logger.error(f"Failed to save error artifacts: {e}")

def safe_click(locator: Locator, timeout: int = 15000):
    """Clicks an element safely with explicit waits."""
    try:
        locator.wait_for(state="visible", timeout=timeout)
        # Using force allows bypassing synthetic overlay elements that sometimes block Playwright
        locator.click(force=True)
    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout: Element not clickable -> {locator}")
        raise e

def safe_fill(locator: Locator, text: str, timeout: int = 15000):
    """Fills an input safely."""
    try:
        locator.wait_for(state="visible", timeout=timeout)
        locator.fill(text)
    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout: Element not visible for filling -> {locator}")
        raise e
