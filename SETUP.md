# Complete Setup & Usage Guide

## Pre-Flight Checklist

Before starting, ensure you have:
- [ ] Python 3.8 or higher installed (`python3 --version`)
- [ ] Internet connection working
- [ ] Your Adamas University student portal credentials
- [ ] The Collageautomationbot project folder

## Step-by-Step Setup

### Step 1: Navigate to Project Folder

```bash
cd /home/dheeraj/Code/actualproject/Collageautomationbot
```

### Step 2: Create Virtual Environment

This isolates the bot's dependencies from your system Python:

```bash
python3 -m venv .venv
```

You should see a `.venv/` folder created.

### Step 3: Activate Virtual Environment

**On Linux/Mac:**
```bash
source .venv/bin/activate
```

**On Windows (Command Prompt):**
```bash
.venv\Scripts\activate
```

**On Windows (PowerShell):**
```bash
.venv\Scripts\Activate.ps1
```

You should see `(.venv)` prefix in your terminal prompt.

### Step 4: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Expected output should show:
```
Successfully installed playwright-X.X.X python-dotenv-X.X.X rich-X.X.X
```

### Step 5: Install Chromium Browser

Playwright needs a browser engine to automate:

```bash
playwright install chromium
```

This downloads ~100MB of browser files. Takes 2-5 minutes depending on internet speed.

## Run Options

### Option 1: Interactive Mode (Recommended for First Run)

```bash
python3 main.py
```

You'll be prompted for:
```
Registration No: [enter your student ID]
Password: [enter password - input is hidden]
```

The bot will then:
1. Launch the browser (silently if headless)
2. Log in
3. Navigate to Feedback
4. Find all pending feedbacks
5. Submit them one by one
6. Print a summary

### Option 2: With .env File (Useful for Multiple Runs)

Skip prompts by using environment variables:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```
LMS_USERNAME=YOUR_STUDENT_ID
LMS_PASSWORD=YOUR_PASSWORD
```

Then run without prompts:
```bash
python3 main.py
```

**⚠️ SECURITY WARNING:**
- Add `.env` to `.gitignore` IMMEDIATELY:
  ```bash
  echo ".env" >> .gitignore
  ```
- Never commit `.env` to version control
- Never share `.env` file with others

### Option 3: Debug Mode (See What's Happening)

```bash
python3 main.py --headful
```

This opens a visible browser window so you can see exactly what the bot is clicking.

### Option 4: Dry-Run Mode (Navigate Without Submitting)

```bash
python3 main.py --dry-run
```

The bot will:
- Log in ✓
- Navigate to Feedback ✓
- Find pending items ✓
- Open feedback forms ✓
- **Skip the actual submit** (test mode)

This is useful to:
- Verify the bot can navigate your specific LMS
- Debug selector issues without submitting
- Practice before real run

### Option 5: Combination Modes

Test everything before submitting:
```bash
python3 main.py --headful --dry-run
```

## First Run Walkthrough

### Running the Bot

1. Open terminal and navigate to project folder:
   ```bash
   cd /home/dheeraj/Code/actualproject/Collageautomationbot
   ```

2. Activate virtual environment:
   ```bash
   source .venv/bin/activate
   ```

3. Run the bot:
   ```bash
   python3 main.py
   ```

4. You'll see:
   ```
   Registration No: █
   ```
   Enter your registration number and press Enter

5. Then:
   ```
   Password: █
   ```
   Enter your password (it won't display, which is normal) and press Enter

6. The bot will start:
   ```
   [INFO] Launching browser...
   [INFO] Opening LMS login page...
   [INFO] Performing login...
   [SUCCESS] Login verified successfully.
   [INFO] Navigating to Feedback section...
   ...
   ```

### Watching Progress

The terminal will show:
- Each subject being processed
- Number of pending feedbacks found
- Each form submission
- Success/failure status
- Summary at the end

Example:
```
[INFO] Found 5 subjects with pending feedback.
[INFO] --- Processing Subject 1/5: Data Structures ---
[INFO] Pending entries found: 12
[INFO] Submitting entry 1/12...
[SUCCESS] Feedback submitted.
[INFO] Submitting entry 2/12...
[SUCCESS] Feedback submitted.
...
[SUMMARY]
Subjects processed: 5
Pending found: 52
Submitted: 52
Skipped: 0
Failed: 0
```

### If Something Goes Wrong

1. Check what went wrong by looking at error messages
2. Run with visible mode to debug:
   ```bash
   python3 main.py --headful
   ```
3. Error artifacts are saved to `errors/` folder with timestamp
4. Check `errors/error_*.html` to see what the page looked like when it failed

## Testing the Setup

### Test 1: Verify Installation

```bash
source .venv/bin/activate
python3 -c "import playwright; print('✓ Playwright installed')"
```

Expected: `✓ Playwright installed`

### Test 2: Does Mock Test Work?

```bash
source .venv/bin/activate
python3 test_mock.py
```

Expected: All 10 tests should pass ✓

This verifies:
- Selectors are correct
- Navigation logic works
- Form detection works

### Test 3: Can You Access the Real LMS?

```bash
source .venv/bin/activate
python3 main.py --dry-run
```

This will:
- Log in with your credentials
- Navigate through the flow
- NOT submit anything (safe to test)
- Show you if there's any error

## Troubleshooting Common Issues

### Error: "ModuleNotFoundError: No module named 'playwright'"

**Cause:** Virtual environment not activated or dependencies not installed

**Solution:**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Error: "python3: command not found"

**Cause:** Python3 not installed or not in PATH

**Solution (Linux/Mac):**
```bash
# Install Python3
sudo apt-get install python3 python3-venv  # Debian/Ubuntu
brew install python3                         # Mac

python3 --version  # Verify
```

### Error: "SyntaxError" in bot files

**Cause:** Corrupted git checkout or encoding issue

**Solution:**
```bash
# Verify Python syntax
python3 -m py_compile bot/*.py

# Reset to clean state
git checkout -- bot/
pip install -r requirements.txt
```

### Browser won't start

**Cause:** Chromium not installed

**Solution:**
```bash
playwright install chromium
```

### Login fails with correct credentials

**Cause:** Selectors may have changed, or network issue

**Solution:**
1. Try with `--headful` to see the actual page:
   ```bash
   python3 main.py --headful
   ```
2. Take a screenshot (visible window)
3. Check if selectors need updating in `bot/selectors.py`
4. Try again

### "No subjects found"

**Cause:** 
- No pending feedback to submit (normal - you've submitted all!)
- Selectors changed on LMS
- Page structure different

**Solution:**
```bash
# Check the real LMS for pending feedback
# Visit: https://adamasknowledgecity.ac.in/student/feedback
# Look for subjects with "Pending" status

# Then try bot again
python3 main.py --headful

# If page looks different, update selectors in bot/selectors.py
```

### Form submission fails silently

**Cause:** Form button selector may be incorrect

**Solution:**
1. Check error artifacts:
   ```bash
   ls -la errors/
   ```
2. Open `errors/error_*.html` in browser to see page structure
3. Update selectors in `bot/selectors.py` if needed
4. Retry

## Performance Expectations

| Operation | Time |
|-----------|------|
| Startup & Login | 5-10 seconds |
| Navigate to Feedback | 2-3 seconds |
| Open Subject | 1-2 seconds |
| Submit Feedback Form | 2-3 seconds |

**Total for 50 pending feedbacks:** ~5-8 minutes

**Factors affecting speed:**
- Internet speed
- LMS server load
- Your computer's disk speed (Playwright is fast)

## Leaving the Bot Running

The bot is safe to run unattended:

```bash
# Redirect output to log file for later review
python3 main.py > feedback_run_$(date +%Y%m%d_%H%M%S).log 2>&1

# Or with .env to not prompt for credentials:
cp .env.example .env
# Edit .env with your credentials
python3 main.py >> feedback_runs.log 2>&1
```

The log files will show what happened.

## What NOT to Do

❌ Don't modify form values (sliders, dropdowns)  
❌ Don't add comments in the comment field  
❌ Don't close browser while bot is running  
❌ Don't commit `.env` file to git  
❌ Don't run with `sudo` unless necessary  
❌ Don't share `.env` file with anyone  

## What the Bot WILL Do

✅ Fill credentials securely  
✅ Log in automatically  
✅ Find all pending feedbacks  
✅ Open each form  
✅ Submit with default values only  
✅ Handle errors gracefully  
✅ Show progress in real-time  
✅ Save error details if something fails  

## Next Steps

1. **Complete initial setup** (run through Steps 1-5)
2. **Test with mock HTML** (`python3 test_mock.py`)
3. **Test with --dry-run** (`python3 main.py --dry-run`)
4. **Run for real** (`python3 main.py`)
5. **Review summary** - verify all feedbacks submitted

## Getting Help

If you encounter issues:

1. Check this file for your error
2. Run with `--headful` to visually debug
3. Check `errors/` folder for HTML dumps
4. Re-read README.md section on selectors
5. Verify credentials are correct
6. Try test mode: `python3 main.py --dry-run`

## Version Information

- **Python:** 3.8+
- **Playwright:** 1.42.0+
- **OS:** Linux, Mac, Windows (WSL2)
- **Last Updated:** April 2, 2026
- **Status:** Production Ready ✅

---

**Ready to submit your feedback?** Run `python3 main.py` and let the automation handle it!
