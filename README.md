# Performance Partner

An internal web app for running 360-degree employee evaluations at Partners In Care. Built to replace spreadsheet-based reviews with a structured, AI-driven interview process and clean aggregated reports.

---

## What it does

**Administrators** create evaluation cycles, enroll participants, and track completion progress. When a cycle is activated, the app automatically generates all evaluation assignments based on staff relationships — self, manager, peer, and direct report.

**Staff** complete their assigned evaluations through a conversational AI interview powered by Claude. Rather than filling out a static form, they're guided through each question naturally, with follow-up prompts when answers are vague or non-specific.

**Reports** aggregate ratings into a radar chart by category and relationship source, with per-question breakdowns and the full interview transcripts available to administrators.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Database | SQLite (single file, no server needed) |
| Templates | Jinja2 |
| Styling | TailwindCSS (CDN) |
| Interactivity | HTMX (CDN) |
| Charts | Chart.js (CDN) |
| AI Interview | Anthropic API — Claude Haiku |
| Auth | bcrypt + itsdangerous signed session cookies |

---

## Running locally

**Requirements:** Python 3.12+, an Anthropic API key.

```bash
# Clone and set up a virtual environment
git clone <repo-url>
cd performancepartner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# At minimum, set ANTHROPIC_API_KEY — see Environment configuration below

# Start the dev server
uvicorn main:app --reload
```

Visit [http://localhost:8000](http://localhost:8000).

The database is created and seeded automatically on first startup — there is no separate seed command to run. `main.py`'s startup hook creates the tables, seeds the admin user, and loads the question bank on every boot (re-runs are no-ops).

To load a full demo cycle with sample users and pre-filled evaluations, run `python seed_demo.py` (and `python seed_demo.py --wipe` to remove it). It only touches its own `@example.com` demo users, so it's safe alongside real data.

### Default admin credentials

| Field | Value |
|---|---|
| Email | `hmis@partnersincareoahu.org` |
| Password | `changeme` |

**Change the password immediately** after first login via Admin → Users.

---

## Environment configuration

All configuration is read from environment variables, loaded from `.env` in local development. Copy `.env.example` to `.env` as a starting point.

| Variable | Required | Default if unset | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | *none* | Claude API key powering the evaluation interview. Without it the chat fails on the first message. |
| `SECRET_KEY` | Production | `dev-secret-key-change-in-production` | Signs session cookies and password-reset tokens. The fallback is fine locally but **must** be overridden in production. |
| `DATABASE_PATH` | No | `performancepartner.db` | Path to the SQLite file. Use the default locally; in production point it at a mounted persistent disk (e.g. `/data/performancepartner.db`). |
| `RESEND_API_KEY` | No | *unset* | Enables password-reset emails. See below. |
| `FROM_EMAIL` | No | `Performance Partner <onboarding@resend.dev>` | `From` header on reset emails. |
| `APP_BASE_URL` | No | `http://localhost:8000` | Base URL used to build reset links in emails. |

Generate a production `SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Rotating `SECRET_KEY` signs out every active session and invalidates any outstanding password-reset links.

### Password reset email (Resend)

Password resets are delivered through [Resend](https://resend.com). The flow is: user submits their address at `/forgot-password` → the app signs a reset token → Resend emails a link to `{APP_BASE_URL}/reset-password?token=...`.

Tokens expire after **1 hour** and are single-use: the token embeds a fragment of the current password hash, so completing a reset automatically invalidates that link and any other outstanding ones. There is no `reset_tokens` table to clean up.

**Setup:**

1. Create an account at [resend.com](https://resend.com) and generate an API key at [resend.com/api-keys](https://resend.com/api-keys).
2. Verify your sending domain under Resend → Domains (add the DNS records it gives you). Until a domain is verified, Resend only delivers to the address that owns the account.
3. Set the three variables:

   ```
   RESEND_API_KEY=re_...
   FROM_EMAIL=Performance Partner <no-reply@partnersincareoahu.org>
   APP_BASE_URL=https://your-deployed-url
   ```

`FROM_EMAIL` must use a domain verified in step 2, or Resend rejects the send. `APP_BASE_URL` must be the app's public URL in production — if it's left at the default, emailed links will point at `localhost` and be unusable.

> **Sends fail silently by design.** `routes/auth.py` catches and swallows any exception from the send, and `/forgot-password` always returns *"If an account exists for that email, a password reset link has been sent"* whether or not the address matched a user. This prevents the form from leaking which emails are registered — but it also means a missing or invalid `RESEND_API_KEY` looks identical to success in the UI. If resets aren't arriving, check the server logs and your Resend dashboard rather than the page output.

**Local development:** leaving `RESEND_API_KEY` unset is fine — everything except password-reset email works normally. To test a reset without configuring Resend, mint a link directly:

```bash
.venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv()
from database import get_db, fetchone
from auth import create_reset_token
with get_db() as c:
    u = fetchone(c, 'SELECT * FROM users WHERE email=?', ('hmis@partnersincareoahu.org',))
print(f\"http://localhost:8000/reset-password?token={create_reset_token(u['id'], u['password_hash'])}\")
"
```

Paste the printed URL into your browser. Alternatively, an admin can change any user's password directly at Admin → Users.

---

## Deploying

See [`DEPLOY.md`](DEPLOY.md) for full instructions for Render, Railway, and Fly.io.

The short version for **Render**:

1. Push this repo to GitHub.
2. New → Web Service → Docker → connect repo.
3. Add a Persistent Disk mounted at `/data`.
4. Set environment variables:
   ```
   SECRET_KEY=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
   DATABASE_PATH=/data/performancepartner.db
   ANTHROPIC_API_KEY=sk-ant-...

   # Optional — omit to disable password-reset emails
   RESEND_API_KEY=re_...
   FROM_EMAIL=Performance Partner <no-reply@partnersincareoahu.org>
   APP_BASE_URL=https://your-app.onrender.com
   ```
5. Deploy.

Set `APP_BASE_URL` to the real deployed URL — reset links are built from it, and the default points at `localhost`. See [Environment configuration](#environment-configuration) for the full reference.

---

## Usage guide

### Setting up an evaluation cycle

1. **Add users** — Admin → Users → New User. Set each person's role (admin / manager / staff), department, and manager. The manager relationship determines how evaluation assignments are generated.

2. **Create a cycle** — Admin → Cycles → New Cycle. Give it a name, optional dates, and select participants.

3. **Activate the cycle** — Click Activate on the cycle card. This generates all evaluation assignments automatically:
   - Everyone evaluates themselves
   - Managers evaluate their direct reports
   - Direct reports evaluate their managers (upward feedback)
   - Everyone else is assigned as peers

4. **Monitor progress** — Click Progress on an active cycle to see completion status for every assignment. Individual report links are available here as well.

5. **Close the cycle** — When evaluations are complete, close the cycle to lock submissions and make reports visible to staff.

### Editing an active cycle

Active cycles can be edited to add or remove participants. Go to Admin → Cycles → Edit on an active cycle. Removing a participant will delete all of their associated evaluation data — the app will warn you if any completed evaluations would be affected.

### The evaluation interview

Staff see their pending evaluations on the dashboard. Clicking Start (or Continue for in-progress evaluations) opens the interview chat.

Claude guides the evaluator through each question section by section. For **peer and report evaluations**, Claude first asks two scoping questions:
- *"Are you on this person's team?"* — unlocks team-specific questions if yes
- *"Are you this person's manager?"* — unlocks manager-specific questions if yes

Likert (1–5) rating questions display inline rating buttons in the chat. Open-ended questions are conversational. If an answer is vague, Claude will ask for a specific example once before moving on.

### Reports

Reports are available to administrators at any time. Staff can view their own report once a cycle is closed.

Each report includes:
- **Summary** — count of completed evaluations by relationship type
- **Radar chart** — average scores by category, with a separate line for each relationship source (self, manager, peer, report)
- **Question breakdown** — horizontal bar charts per question, colored by relationship
- **Interview transcripts** — full conversation for each evaluator (peer/report evaluators are anonymized for non-admins)

Navigate to reports from the Progress page, or from the Dashboard under *My Reports* (for closed cycles).

---

## Question bank

The evaluation questions are organized into scopes:

| Scope | Shown to |
|---|---|
| General | All evaluators |
| Team-specific | Evaluators who confirm they work on the same team |
| Manager-specific | Managers and self-evaluations |
| Dept-specific | Evaluators in the same department as the subject |

Questions can be managed at Admin → Questions. Department-specific questions are currently configured for CES, Finance, and HMIS.

---

## Project structure

```
performancepartner/
├── main.py              # App entry point, router registration, startup hooks
├── database.py          # Schema creation, seed functions, DB helpers
├── auth.py              # Session cookies, password hashing, auth dependencies
├── config.py            # Jinja2 setup, custom filters, render helper
├── interview.py         # Claude API integration, system prompt builder
├── email_utils.py       # Resend integration for password-reset emails
├── seed.py              # Question bank seed data
├── seed_demo.py         # Optional demo cycle + sample users (--wipe to remove)
├── routes/
│   ├── auth.py          # Login / logout
│   ├── dashboard.py     # Staff dashboard
│   ├── admin.py         # Cycle, user, and question management
│   ├── eval.py          # Chat interview endpoints
│   └── reports.py       # Report generation
├── templates/           # Jinja2 HTML templates
├── static/              # Logo and favicon
├── Dockerfile
├── DEPLOY.md
└── .env.example
```
