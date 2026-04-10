# Contributing to Adamas Auto-Feedback Bot

First off — thanks for taking the time to contribute! 🎉  
Every bug report, code improvement, and documentation fix makes this better for every Adamas student.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Getting Started (Dev Setup)](#getting-started-dev-setup)
- [Branch & Commit Conventions](#branch--commit-conventions)
- [Pull Request Process](#pull-request-process)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Project Structure Cheatsheet](#project-structure-cheatsheet)
- [Good First Issues](#good-first-issues)

---

## Code of Conduct

Be kind and respectful. This is a student project — everyone here is learning. Harassment, discrimination, or toxic behaviour will result in a ban. If something feels off, open an issue or email the maintainer directly.

---

## Ways to Contribute

You don't have to write code to contribute:

| Type | Examples |
|------|---------|
| 🐛 **Bug reports** | Login fails, form not submitted, UI broken on mobile |
| ✨ **Feature requests** | Email notification on finish, Docker support |
| 📖 **Documentation** | Fix typos, add examples, improve troubleshooting guide |
| 🧪 **Testing** | Try the bot on a different LMS version and report back |
| 🔧 **Code** | Fix a bug, add a feature, improve selectors |
| 🌐 **Translations** | README in Bengali, Hindi, or other languages |

---

## Getting Started (Dev Setup)

### 1. Fork & Clone

```bash
# Fork the repo on GitHub first, then:
git clone https://github.com/<Dheerajkumar69>/Collageautomationbot.git
cd Collageautomationbot
```

### 2. Set Up Python Backend

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 3. Set Up Next.js Frontend

```bash
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

### 4. Run Locally

```bash
# Terminal 1 — backend
source .venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 5. Run the Mock Tests

Before opening a PR, make sure mock tests still pass:

```bash
source .venv/bin/activate
python3 test_mock.py
```

All 10 tests must pass ✅.

---

## Branch & Commit Conventions

### Branch naming

```
feat/short-description       # new feature
fix/short-description        # bug fix
docs/short-description       # documentation only
chore/short-description      # tooling, deps, config
refactor/short-description   # code restructure, no behaviour change
```

### Commit messages — [Conventional Commits](https://www.conventionalcommits.org/)

```
feat: add email notification on automation complete
fix: handle LMS login redirect timeout gracefully
docs: add Docker setup to README
chore: upgrade Playwright to 1.50
refactor: extract queue helpers into separate module
```

Keep commits small and focused — one logical change per commit.

---

## Pull Request Process

1. **Create your branch** from `main`:
   ```bash
   git checkout -b feat/your-feature
   ```

2. **Make your changes** — keep them focused and minimal.

3. **Run mock tests** and make sure they pass:
   ```bash
   python3 test_mock.py
   ```

4. **Update documentation** if your change affects behaviour (README, SETUP.md, env var tables, etc.).

5. **Push and open a PR**:
   ```bash
   git push origin feat/your-feature
   ```
   Then open a PR on GitHub against the `main` branch.

6. **Fill in the PR template** — describe *what* changed and *why*.

7. A maintainer will review, leave comments, and merge when it's ready. Please be patient — this is a solo-maintained project.

### PR checklist

- [ ] `python3 test_mock.py` passes
- [ ] No hardcoded credentials or real student IDs anywhere
- [ ] `.env` not committed
- [ ] Commit messages follow Conventional Commits
- [ ] Docs updated if behaviour changed

---

## Reporting Bugs

Open a [GitHub Issue](https://github.com/Dheerajkumar69/Collageautomationbot/issues/new) and include:

- **What you did** (steps to reproduce)
- **What you expected** to happen
- **What actually happened** (paste the terminal output or screenshot)
- **Environment:** OS, Python version, browser (for frontend issues)
- **Logs** from `errors/` folder if available

> ⚠️ **Never include your real LMS credentials in an issue.** Sanitize any logs you paste.

---

## Suggesting Features

Open a [GitHub Issue](https://github.com/Dheerajkumar69/Collageautomationbot/issues/new) with the label `enhancement` and describe:

- The problem you're trying to solve
- Your proposed solution
- Any alternatives you considered

---

## Project Structure Cheatsheet

| File / Folder | What to touch for… |
|---|---|
| `bot/selectors.py` | LMS page element selectors changed |
| `bot/feedback.py` | Feedback form submission logic |
| `bot/auth.py` | Login flow, student name extraction |
| `bot/browser.py` | Playwright / Chromium launch settings |
| `server.py` | API routes, SSE streaming, queue logic |
| `src/app/page.tsx` | Frontend UI — all in one file |
| `render_waker.py` | Keep-alive pinger for Render free tier |
| `render.yaml` | Render deployment config |
| `netlify.toml` | Netlify deployment config |

---

## Good First Issues

New to the project? Look for issues labelled [`good first issue`](https://github.com/Dheerajkumar69/Collageautomationbot/issues?q=label%3A%22good+first+issue%22). Some ideas:

- 📱 Improve mobile layout of the terminal panel
- 🐳 Add a `docker-compose.yml` for local dev
- 📧 Add a completion email/webhook notification option
- 🌐 Translate README to Bengali or Hindi
- 🔁 Add retry logic for individual failed form submissions

---

Thanks again! Every contribution matters. 🙌
