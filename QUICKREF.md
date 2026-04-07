# Quick Reference Guide

## Quick Start (TL;DR)

```bash
# Setup (one-time)
cd /home/dheeraj/Code/actualproject/Collageautomationbot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Run (every time)
source .venv/bin/activate
python3 main.py
```

## Common Commands

| Task | Command |
|------|---------|
| **Setup** | `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium` |
| **Validate Setup** | `python3 validate.py` |
| **Test with Mock HTML** | `python3 test_mock.py` |
| **Run Normally** | `python3 main.py` |
| **Debug Mode (see browser)** | `python3 main.py --headful` |
| **Test (no submit)** | `python3 main.py --dry-run` |
| **Debug + Test** | `python3 main.py --headful --dry-run` |

## Command Line Flags

```
python3 main.py [options]

Options:
  --headful       Show browser window (default: headless/hidden)
  --dry-run       Navigate but don't submit (test mode)
  --help          Show this help
```

## Cloud API Runtime Behavior

- API runs are always headless and non-interactive.
- The backend executes one run at a time and uses FIFO queueing.
- Maximum waiting queue depth is 5. Extra requests get HTTP 429.
- While queued, frontend receives live queue position updates.
- While running without new bot output, frontend receives heartbeat updates.
- Error artifacts are disabled for server/API runs by default.

### Relevant Runtime Env Vars (Render web service)

- `RUN_QUEUE_MAX_DEPTH` (default `5`)
- `RUN_QUEUE_HEARTBEAT_SECONDS` (default `5`)
- `RUN_STREAM_HEARTBEAT_SECONDS` (default `15`)
- `BOT_NON_INTERACTIVE` (default `1` in Render)
- `BOT_DISABLE_ERROR_ARTIFACTS` (default `1` in Render)
- `BOT_SERVER_MODE` (default `1` in Render)

## Environment Setup (First Time)

1. **Enter project directory:**
   ```bash
   cd /home/dheeraj/Code/actualproject/Collageautomationbot
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv .venv
   ```

3. **Activate virtual environment:**
   ```bash
   source .venv/bin/activate
   ```
   (You should see `(.venv)` in terminal prompt)

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

5. **Validate everything works:**
   ```bash
   python3 validate.py
   ```

## Activation (Every Session)

Always do this before running the bot:

```bash
cd /home/dheeraj/Code/actualproject/Collageautomationbot
source .venv/bin/activate
python3 main.py
```

Or with .env file (no prompts):
```bash
source .venv/bin/activate
python3 main.py
```

## Understanding Output

### Successful Run
```
[INFO] Opening LMS login page...
[SUCCESS] Login verified successfully.
[INFO] Navigating to Feedback section...
[INFO] Found 8 subjects with pending feedback.
[INFO] --- Processing Subject 1/8: Subject Name ---
[INFO] Pending entries found: 15
[SUCCESS] Feedback submitted.
...
[SUMMARY]
Subjects processed: 8
Pending found: 120
Submitted: 120
Skipped: 0
Failed: 0
```

### What Each Log Level Means
- `[INFO]` — Normal progress information
- `[SUCCESS]` — Action completed successfully
- `[WARNING]` — Something unexpected but recovering
- `[ERROR]` — Something went wrong

## Troubleshooting Quick Fixes

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'playwright'` | `pip install -r requirements.txt` |
| `CommandNotFoundError: python3` | Install Python: `sudo apt-get install python3` |
| `Browser won't start` | Run `playwright install chromium` |
| `Login failed` | Try with `--headful` to see what's wrong |
| `SyntaxError in bot files` | This shouldn't happen - means corruption |
| `No subjects found` | Normal if no pending feedback (check LMS manually) |

## File Structure Reference

```
Collageautomationbot/
├── main.py                 ← Entry point (run this)
├── validate.py             ← Pre-flight check
├── test_mock.py            ← Test with mock HTML
├── requirements.txt        ← Dependencies
├── README.md               ← Full documentation
├── SETUP.md                ← Detailed setup guide
├── .env.example            ← Credentials template (copy to .env)
│
├── bot/                    ← Bot package
│   ├── __init__.py         ← Package marker
│   ├── config.py           ← Configuration
│   ├── logger.py           ← Logging setup
│   ├── selectors.py        ← UI element selectors
│   ├── browser.py          ← Browser management
│   ├── auth.py             ← Login logic
│   ├── navigation.py       ← LMS navigation
│   ├── feedback.py         ← Feedback processing
│   ├── utils.py            ← Helper functions
│   └── models.py           ← Data classes
│
├── mock_tests/             ← Mock HTML for testing
│   ├── login.html
│   ├── dashboard.html
│   ├── feedback.html
│   ├── subject.html
│   └── form.html
│
└── errors/                 ← Error artifacts (auto-created)
    └── error_*.html,png    ← Saved on failures
```

## Using .env File

### Create
```bash
cp .env.example .env
```

### Edit
```
LMS_USERNAME=YOUR_STUDENT_ID
LMS_PASSWORD=YOUR_PASSWORD
```

### Secure
```bash
echo ".env" >> .gitignore  # Never commit!
chmod 600 .env             # Read-only by owner
```

### Run
```bash
python3 main.py            # No prompts!
```

## Performance Notes

- **Total time for 50 items:** 5-10 minutes
- **Per form submit:** 2-3 seconds
- **Speed limited by:** LMS server, network latency
- **Headful mode is slower** (rendering overhead)

## Useful Git Commands (If Using Version Control)

```bash
# Never commit credentials
echo ".env" >> .gitignore
echo "errors/" >> .gitignore
echo ".venv/" >> .gitignore

# Review changes (safe before commit)
git status
git diff bot/

# Save your changes safely
git add -A
git commit -m "Bot configuration updates"
```

## Keyboard Shortcuts in Terminal

| Key | Action |
|-----|--------|
| `Ctrl+C` | Stop bot (graceful shutdown) |
| `Ctrl+Z` | Suspend (might not work with Playwright) |
| `Q` | Quit if bot prompts for something |
| `Up Arrow` | Repeat last command |

## What the Bot Does (Flow)

1. Reads credentials (from prompt or .env)
2. Launches Chromium browser
3. Navigates to `https://adamasknowledgecity.ac.in/student/login`
4. Fills login form
5. Verifies login by checking for sidebar
6. Clicks "Feedback" in navigation
7. Finds all subject cards
8. For each subject:
   - Opens subject details
   - Counts pending feedback entries
   - For each entry:
     - Clicks "Give Feedback"
     - Waits for form to load
     - In dry-run: goes back
     - In real mode: clicks "Submit Feedback"
     - Waits for success
9. Returns to Feedback dashboard
10. Repeats for next subject
11. Prints summary
12. Closes browser

## Advanced: Custom Dry-Run

Test different scenarios:

```bash
# Check login works
python3 main.py --dry-run

# Debug selector issues
python3 main.py --headful --dry-run

# Actually submit (remove --dry-run)
python3 main.py
```

## When to Use Which Mode

| Scenario | Command | Why |
|----------|---------|-----|
| First time | `--headful --dry-run` | See what's happening, don't submit |
| Testing selectors | `--headful` | Visually debug |
| Debugging failure | `--headful` + check `errors/` | See page state + artifacts |
| Production run | Just `main.py` | Quick, silent, no prompts (with .env) |
| Offline testing | `test_mock.py` | No internet needed |

## Version & Support Info

- **Bot Version:** 2.0 (Fixed & Production Ready)
- **Python:** 3.8+
- **Status:** ✅ All tests passing
- **Last Updated:** April 2, 2026

---

**Need more help?** Read:
- `README.md` — Complete documentation
- `SETUP.md` — Detailed setup walkthrough  
- `errors/*.html` — See what happened on failure
