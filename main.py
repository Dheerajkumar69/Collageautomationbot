import argparse
import getpass
import os
import sys
from bot.config import Config
from bot.logger import logger, print_summary
from bot.browser import BrowserManager
from bot.auth import AuthHandler
from bot.navigation import NavigationHandler
from bot.feedback import FeedbackProcessor


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def parse_args():
    parser = argparse.ArgumentParser(description="LMS Feedback Automation Bot")
    parser.add_argument("--headful", action="store_true", help="Run with visible browser (default is headless)")
    parser.add_argument("--dry-run", action="store_true", help="Navigate but do not actually click Submit")
    return parser.parse_args()

def main():
    args = parse_args()
    
    config = Config()
    config.headless = not args.headful
    config.dry_run = args.dry_run
    
    non_interactive = _env_flag("BOT_NON_INTERACTIVE") or _env_flag("BOT_SERVER_MODE")

    # Prompt only in local interactive runs.
    if not config.username:
        if non_interactive:
            logger.error("Missing LMS_USERNAME in non-interactive mode.")
            sys.exit(1)
        config.username = input("Registration No: ").strip()
    if not config.password:
        if non_interactive:
            logger.error("Missing LMS_PASSWORD in non-interactive mode.")
            sys.exit(1)
        config.password = getpass.getpass("Password: ")
        
    if not config.validate_credentials():
        logger.error("Credentials cannot be empty.")
        sys.exit(1)

    browser_manager = BrowserManager(config)
    
    try:
        page = browser_manager.start()
        
        auth = AuthHandler(page, config)
        auth.login()
        
        nav = NavigationHandler(page)
        nav.go_to_feedback()
        
        processor = FeedbackProcessor(page, config, browser_manager)
        summary = processor.process_all()
        
        print_summary(summary)
        
    except KeyboardInterrupt:
        logger.info("\nProcess interrupted by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Automation stopped due to error: {e}")
        sys.exit(1)
    finally:
        browser_manager.close()

if __name__ == "__main__":
    main()
