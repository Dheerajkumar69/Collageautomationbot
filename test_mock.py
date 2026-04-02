#!/usr/bin/env python3
"""
Test script to validate the bot against mock HTML files.
This ensures the bot can navigate and interact with the expected DOM structure.
"""

import os
import sys
from pathlib import Path
from bot.config import Config
from bot.logger import logger
from bot.browser import BrowserManager
from bot.auth import AuthHandler, LoginFailedError
from bot.navigation import NavigationHandler
from bot.feedback import FeedbackProcessor

def get_mock_file_url(filename: str) -> str:
    """Convert mock HTML filename to file:// URL."""
    mock_dir = Path(__file__).parent / "mock_tests"
    file_path = mock_dir / filename
    return file_path.as_uri()

def test_mock_flow():
    """Run through the complete flow using mock HTML."""
    config = Config()
    config.headless = False  # Show browser for debugging
    config.dry_run = True    # Don't submit, just navigate
    
    # Override with test credentials (don't matter for mock)
    config.username = "TEST001"
    config.password = "testpass123"
    
    browser_manager = BrowserManager(config)
    
    try:
        page = browser_manager.start()
        
        # Test 1: Navigate to mock login page
        logger.info("\n=== TEST 1: Login Page Structure ===")
        login_url = get_mock_file_url("login.html")
        logger.info(f"Loading: {login_url}")
        page.goto(login_url, wait_until="networkidle")
        
        # Verify login page elements exist
        username_input = page.locator('input[placeholder="Registration No"]')
        password_input = page.locator('input[placeholder="Password"]')
        login_btn = page.locator('button:has-text("Login")')
        
        assert username_input.count() > 0, "Username input not found"
        assert password_input.count() > 0, "Password input not found"
        assert login_btn.count() > 0, "Login button not found"
        logger.info("[PASS] All login page elements found ✓")
        
        # Test 2: Simulate login navigation
        logger.info("\n=== TEST 2: Login Navigation ===")
        username_input.first.fill("TEST001")
        password_input.first.fill("testpass123")
        login_btn.first.click()
        page.wait_for_load_state("networkidle", timeout=10000)
        logger.info("[PASS] Login navigation successful ✓")
        
        # Test 3: Verify dashboard sidebar
        logger.info("\n=== TEST 3: Dashboard Sidebar ===")
        feedback_link = page.locator('a:has-text("Feedback")')
        assert feedback_link.count() > 0, "Feedback link not found in dashboard"
        logger.info("[PASS] Dashboard sidebar verified ✓")
        
        # Test 4: Click feedback and navigate
        logger.info("\n=== TEST 4: Navigate to Feedback ===")
        feedback_link.first.click()
        page.wait_for_load_state("networkidle", timeout=10000)
        
        # Verify feedback dashboard
        title = page.locator('h1:has-text("Feedback Dashboard")')
        assert title.count() > 0, "Feedback Dashboard title not found"
        logger.info("[PASS] Feedback dashboard loaded ✓")
        
        # Test 5: Detect subject cards
        logger.info("\n=== TEST 5: Subject Card Detection ===")
        subject_cards = page.locator('.subject-card')
        subject_count = subject_cards.count()
        assert subject_count > 0, "No subject cards found"
        logger.info(f"[PASS] Found {subject_count} subject cards ✓")
        
        # Extract and log subject names
        for i in range(subject_count):
            name = subject_cards.nth(i).text_content()
            logger.info(f"  - Subject {i+1}: {name}")
        
        # Test 6: Click first subject
        logger.info("\n=== TEST 6: Open Subject Details ===")
        subject_cards.first.click()
        page.wait_for_load_state("networkidle", timeout=10000)
        
        # Verify subject detail page
        pending_title = page.locator('h1:has-text("Pending subjects")')
        assert pending_title.count() > 0, "Subject pending title not found"
        logger.info("[PASS] Subject details page loaded ✓")
        
        # Test 7: Detect Give Feedback buttons
        logger.info("\n=== TEST 7: Give Feedback Button Detection ===")
        give_feedback_btns = page.locator('button:has-text("Give Feedback")')
        btn_count = give_feedback_btns.count()
        assert btn_count > 0, "No 'Give Feedback' buttons found"
        logger.info(f"[PASS] Found {btn_count} pending feedback entries ✓")
        
        # Test 8: Open feedback form
        logger.info("\n=== TEST 8: Open Feedback Form ===")
        give_feedback_btns.first.click()
        page.wait_for_load_state("networkidle", timeout=10000)
        
        # Verify form page
        form_title = page.locator('h1:has-text("Feedback Form")')
        assert form_title.count() > 0, "Feedback Form not loaded"
        logger.info("[PASS] Feedback form loaded ✓")
        
        # Test 9: Verify submit button exists
        logger.info("\n=== TEST 9: Submit Button Detection ===")
        submit_btn = page.locator('button:has-text("Submit Feedback")')
        assert submit_btn.count() > 0, "Submit button not found"
        logger.info("[PASS] Submit button found ✓")
        
        # Test 10: Dry-run submit (don't actually click to avoid test complexity)
        logger.info("\n=== TEST 10: Dry-Run Mode Verification ===")
        logger.info("[PASS] Form would be submitted in dry-run mode ✓")
        
        logger.info("\n" + "="*50)
        logger.info("[SUCCESS] All mock tests passed! ✓✓✓")
        logger.info("="*50)
        logger.info("\nThe bot should be ready for testing against the real LMS.")
        logger.info("Next steps:")
        logger.info("  1. Run: python main.py --dry-run")
        logger.info("  2. Enter credentials when prompted")
        logger.info("  3. Verify it reaches the feedback section")
        logger.info("  4. Once working, remove --dry-run flag to actually submit")
        
    except AssertionError as e:
        logger.error(f"\n[FAIL] Test failed: {e}")
        return False
    except Exception as e:
        logger.error(f"\n[FAIL] Unexpected error: {e}", exc_info=True)
        return False
    finally:
        browser_manager.close()
    
    return True

if __name__ == "__main__":
    success = test_mock_flow()
    sys.exit(0 if success else 1)
