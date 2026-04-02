#!/usr/bin/env python3
"""
Pre-flight validation script.
Run this before the first real execution to ensure all systems go.
"""

import sys
import os
from pathlib import Path

def check_python_version():
    """Verify Python 3.8+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"❌ Python version {version.major}.{version.minor} is too old (need 3.8+)")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} - OK")
    return True

def check_dependencies():
    """Verify required packages are installed"""
    required = {
        'playwright': 'Playwright (browser automation)',
        'dotenv': 'python-dotenv (env file support)',
        'rich': 'Rich (terminal formatting)',
    }
    
    missing = []
    for module, name in required.items():
        try:
            __import__(module)
            print(f"✅ {name} - installed")
        except ImportError:
            print(f"❌ {name} - NOT FOUND")
            missing.append(name)
    
    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print("Fix with: pip install -r requirements.txt")
        return False
    return True

def check_project_structure():
    """Verify all required files exist"""
    required_files = [
        'main.py',
        'requirements.txt',
        'README.md',
        'SETUP.md',
        '.env.example',
        'bot/__init__.py',
        'bot/auth.py',
        'bot/browser.py',
        'bot/config.py',
        'bot/feedback.py',
        'bot/logger.py',
        'bot/models.py',
        'bot/navigation.py',
        'bot/selectors.py',
        'bot/utils.py',
        'test_mock.py',
    ]
    
    missing = []
    for file_path in required_files:
        p = Path(file_path)
        if p.exists():
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} - MISSING")
            missing.append(file_path)
    
    if missing:
        print(f"\nMissing files: {', '.join(missing)}")
        return False
    return True

def check_syntax():
    """Verify Python syntax in all modules"""
    import ast
    
    modules = [
        'main.py',
        'bot/auth.py',
        'bot/browser.py',
        'bot/config.py',
        'bot/feedback.py',
        'bot/logger.py',
        'bot/models.py',
        'bot/navigation.py',
        'bot/selectors.py',
        'bot/utils.py',
    ]
    
    errors = []
    for module in modules:
        try:
            with open(module) as f:
                ast.parse(f.read())
            print(f"✅ {module} - syntax OK")
        except SyntaxError as e:
            print(f"❌ {module} - SYNTAX ERROR: {e}")
            errors.append((module, e))
    
    if errors:
        print(f"\n{len(errors)} syntax error(s) found!")
        return False
    return True

def check_imports():
    """Verify all imports work"""
    try:
        print("\nTesting imports...")
        from bot.config import Config
        print("✅ bot.config.Config")
        
        from bot.logger import logger
        print("✅ bot.logger.logger")
        
        from bot.browser import BrowserManager
        print("✅ bot.browser.BrowserManager")
        
        from bot.auth import AuthHandler
        print("✅ bot.auth.AuthHandler")
        
        from bot.navigation import NavigationHandler
        print("✅ bot.navigation.NavigationHandler")
        
        from bot.feedback import FeedbackProcessor
        print("✅ bot.feedback.FeedbackProcessor")
        
        from bot.models import ProgressSummary
        print("✅ bot.models.ProgressSummary")
        
        print("\nAll imports successful!")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def check_env_file():
    """Check if .env file exists and is properly formatted"""
    env_path = Path('.env')
    
    if not env_path.exists():
        print("ℹ️  .env file not found (OK - credentials will be prompted)")
        return True
    
    try:
        with open('.env') as f:
            content = f.read()
        
        # Basic validation
        if 'LMS_USERNAME' in content:
            print("✅ .env file exists and contains LMS_USERNAME")
        else:
            print("⚠️  .env exists but LMS_USERNAME not set")
        
        if 'LMS_PASSWORD' in content:
            print("✅ .env file contains LMS_PASSWORD")
            # Verify password is not the placeholder
            if 'your_password_here' in content:
                print("⚠️  LMS_PASSWORD still has placeholder value - update before running!")
        else:
            print("⚠️  .env file doesn't contain LMS_PASSWORD - will be prompted")
        
        return True
    except Exception as e:
        print(f"⚠️  Error reading .env: {e}")
        return True  # Don't fail, just warn

def check_mock_files():
    """Verify mock test files exist"""
    mock_files = [
        'mock_tests/login.html',
        'mock_tests/dashboard.html',
        'mock_tests/feedback.html',
        'mock_tests/subject.html',
        'mock_tests/form.html',
    ]
    
    missing = []
    for file_path in mock_files:
        p = Path(file_path)
        if p.exists():
            print(f"✅ {file_path}")
        else:
            print(f"⚠️  {file_path} - missing (won't affect real runs)")
            missing.append(file_path)
    
    return len(missing) == 0

def main():
    print("=" * 60)
    print("LMS Feedback Bot - Pre-Flight Validation")
    print("=" * 60)
    print()
    
    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("Project Structure", check_project_structure),
        ("Python Syntax", check_syntax),
        ("Module Imports", check_imports),
        ("Configuration Files", check_env_file),
        ("Mock Test Files", check_mock_files),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\n{'=' * 60}")
        print(f"Checking: {name}")
        print('=' * 60)
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ UNEXPECTED ERROR: {e}")
            results.append((name, False))
    
    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print('=' * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Result: {passed}/{total} checks passed")
    print()
    
    if passed == total:
        print("=" * 60)
        print("✅ ALL CHECKS PASSED - Bot is ready to run!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Test mock flow:   python3 test_mock.py")
        print("  2. Dry-run test:     python3 main.py --dry-run")
        print("  3. Real run:         python3 main.py")
        print()
        return 0
    else:
        print("=" * 60)
        print("❌ SOME CHECKS FAILED - Fix issues before running")
        print("=" * 60)
        print()
        print("Read the output above and fix any failures.")
        print("Common fixes:")
        print("  - pip install -r requirements.txt")
        print("  - playwright install chromium")
        print("  - Check Python version: python3 --version")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())
