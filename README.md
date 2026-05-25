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
# Edit .env and fill in SECRET_KEY, DATABASE_PATH, and ANTHROPIC_API_KEY

# Start the dev server
uvicorn main:app --reload
```

Visit [http://localhost:8000](http://localhost:8000).

The database is created and seeded automatically on first startup.

### Default admin credentials

| Field | Value |
|---|---|
| Email | `hmis@partnersincareoahu.org` |
| Password | `changeme` |

**Change the password immediately** after first login via Admin → Users.

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
   ```
5. Deploy.

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
├── seed.py              # Question bank seed data
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
