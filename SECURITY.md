# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` branch (latest) | ✅ Active |
| Older commits / forks | ❌ Not supported |

Only the current `main` branch receives security fixes. If you are running an old fork, please update before reporting.

---

## Reporting a Vulnerability

**Please do NOT open a public GitHub Issue for security vulnerabilities.**

Public issues are visible to everyone — including bad actors — before a fix is in place.

### How to report

Send an email to:

**📧 dheerajsingh9933@gmail.com**

Use the subject line: `[SECURITY] Collageautomationbot — <brief description>`

### What to include

Please provide as much detail as possible:

- **Description** of the vulnerability and its potential impact
- **Steps to reproduce** (proof-of-concept is helpful but not required)
- **Affected component** (`server.py`, frontend, bot, deploy config, etc.)
- **Your suggested fix** (optional — greatly appreciated)

### What to expect

| Timeline | Action |
|----------|--------|
| **Within 48 hours** | Acknowledgement of your report |
| **Within 7 days** | Initial assessment and severity classification |
| **Within 30 days** | Fix released (or a clear timeline if more complex) |
| **After fix is released** | Public disclosure coordinated with you |

You will be credited in the release notes unless you prefer to remain anonymous.

---

## Scope — What We Care About

### In scope ✅

| Issue | Example |
|-------|---------|
| Credential exposure | Server-side logs leaking passwords to other users |
| Injection / RCE | Untrusted input reaching `subprocess` without sanitization |
| Auth bypass | Accessing another user's run stream without their `request_id` |
| Sensitive data in responses | `X-Request-Id` or queue endpoints leaking other users' full credentials |
| Dependency with known CVE | A pinned package with a public exploit |

### Out of scope ❌

| Issue | Reason |
|-------|--------|
| Credentials stored in `.env` on your own machine | Intended usage — your machine, your responsibility |
| Render / Netlify platform vulnerabilities | Report those to Render/Netlify directly |
| Rate-limiting / DoS on Render free tier | The free tier has its own natural limits; this is expected |
| Self-XSS (you injecting scripts in your own browser) | Not a real attack vector |
| Social engineering | Out of scope for this project |

---

## Important Notes on How This Project Handles Credentials

This project takes credential safety seriously:

- 🔒 **Credentials are never stored** — they are held in memory per-request only and discarded when the request ends
- 🧹 **All log output is sanitized** — the server strips passwords and tokens before streaming to the client (see `_sanitize_stream_line` in `server.py`)
- 🚫 **Credentials are not passed via command-line args** — they are passed as environment variables to the bot subprocess, which prevents them appearing in `ps aux` output
- 📁 **`.env` is gitignored** — the project's `.gitignore` explicitly excludes all `.env*` files

If you find that any of these guarantees are violated, **that is absolutely in scope for a security report**.

---

## Disclosure Policy

This project follows [responsible disclosure](https://cheatsheetseries.owasp.org/cheatsheets/Vulnerability_Disclosure_Cheat_Sheet.html):

1. Reporter notifies maintainer privately
2. Maintainer acknowledges and investigates
3. Fix is developed and tested
4. Fix is released
5. Public disclosure (CVE if applicable, release notes credit)

We ask that you give us reasonable time to fix the issue before publishing details publicly. We commit to doing the same — we will not ask you to delay disclosure indefinitely.

---

## Hall of Fame

> *No vulnerabilities reported yet. Be the first responsible discloser!*

We will list responsible reporters here (with permission) after their reported issue is fixed.

---

Thank you for helping keep this project and its users safe. 🛡️
