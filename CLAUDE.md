# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dev server

```bash
.venv/bin/uvicorn main:app --port 8000 --reload
```

Requires a `.env` file — see `.env.example` for the three required vars (`SECRET_KEY`, `DATABASE_PATH`, `ANTHROPIC_API_KEY`).

The database is created and seeded automatically on startup (`create_tables()` + `seed_admin()` + `seed_questions()`). Re-running `seed.py` directly is safe (skips duplicates).

Default admin login: `hmis@partnersincareoahu.org` / `changeme`

## Architecture

Single-file-per-concern FastAPI app. No ORM — raw SQLite via a thin `database.py` helper (`get_db()` context manager, `fetchone()`, `fetchall()`). Templates are Jinja2; interactivity is vanilla JS with `fetch()` (no HTMX despite the README mention). Tailwind is loaded from CDN.

**Request flow:**
1. `main.py` — mounts routers, handles auth exceptions globally, runs startup hooks
2. `auth.py` — session cookie signed with `itsdangerous`; `require_user()` / `require_admin()` are called at the top of every route handler (not as FastAPI dependencies)
3. `config.py` — `render()` wrapper that auto-injects `user` into every template context; also registers Jinja2 filters (`relationship_label`, `scope_label`, `qtype_label`)
4. `routes/` — one file per domain area (auth, dashboard, admin, eval, reports)

**Eval chat flow** (`routes/eval.py` + `interview.py`):
- `GET /eval/{id}` renders `eval/chat.html` with existing `conversation_turns`
- `POST /eval/{id}/message` receives the user message, optionally intercepts `RATING:N:value` to write the rating to `responses`, stores the turn, calls `interview.call_claude()`, stores the reply (with its `section`, overridden by the DB when the turn poses a listed question — see below), and returns JSON `{reply, rating_ids, completed}`
- The frontend JS appends the reply bubble and, when `rating_ids` is non-empty, renders clickable 1–5 buttons that send `RATING:{question_id}:{value}` as the next message
- Rating buttons are gated server-side by `_rating_ids_for()`: they appear only when the model sets `asking_question_id` **and** the DB confirms that question is an active `likert` that isn't already rated. There are no text markers in the response — the model never decides button visibility on its own
- The question ID is persisted to `conversation_turns.rating_question_id`, so `GET /eval/{id}` can re-render still-pending buttons after a page reload (`pending_rating_id`)
- Completion comes from the tool's `interview_complete` field returned by `call_claude()`; the route then marks the assignment `completed`

**Cycle lifecycle:** draft → active → closed
- Activating a draft cycle generates all `assignments` rows (self + peer + manager + report combinations) based on `users.manager_id` relationships
- Questions are scoped: `general`, `team_specific`, `manager_specific`, `dept_specific` — the system prompt passed to Claude includes only the relevant scopes per evaluator relationship
- Reports are only visible to the subject once the cycle is closed; admins/managers can view any report at any time

## Schema

Key tables: `users`, `questions`, `cycles`, `cycle_participants`, `assignments`, `conversation_turns`, `responses`

`assignments.relationship` is one of: `self`, `manager`, `peer`, `report`

`conversation_turns.rating_question_id` (nullable) records the likert question an assistant turn posed, so pending rating buttons survive a page reload. It is **not** in the `CREATE TABLE` — it's added by an `ALTER TABLE` migration in `create_tables()` wrapped in a try/except, so grepping the schema block alone will miss it.

`conversation_turns.section` (nullable TEXT) records the interview section the model declared for an assistant turn — a `questions.category` string, `Introduction`, or `Closing`. Same migration pattern as `rating_question_id` (try/except `ALTER TABLE` in `create_tables()`, not in the `CREATE TABLE`). The report page groups a transcript's turns by it to render section headers; turns with NULL (recorded before the column existed) render without headers.

`questions.question_type` controls interview behavior: `likert` → rating buttons, `text` → open-ended, `goal` → open-ended (goal-framed)

`questions.scope`: `general` (always asked), `team_specific` (on same team), `manager_specific` (manager or self), `dept_specific` (evaluee's department match)

## AI model

`interview.py` uses `claude-haiku-4-5-20251001`. The system prompt is built fresh per request from the current questions in the DB — no caching. The model is forced (`tool_choice`) to answer every turn via the `interview_turn` tool; `call_claude()` returns `(display_text, completed, asking_question_id, section)` read straight from validated tool input. The route derives rating-button visibility from `asking_question_id` + the question's `question_type` in the DB (no text markers).

The tool also requires a `last_answer` field (`specific` / `vague` / `declined` / `not_applicable`) that the model must fill in **before** writing `message`. Nothing server-side reads it — it exists to force the model to classify the evaluator's reply explicitly, which is what makes the follow-up probes fire reliably. Both rules consume it: RULE 1 uses it to decide whether a low rating (≤3) needs a *second* follow-up, and RULE 2 uses it to decide whether an open-ended answer needs a probe. It is listed first in the schema deliberately (strict tool use generates fields in schema order), so the classification precedes the reply rather than rationalizing it. Removing the field, reordering it after `message`, or dropping it from `required` regresses follow-up behavior.

Probe caps differ by path: RULE 1 allows **two** follow-ups on a low rating (the initial "why?" plus one more if the answer is vague); RULE 2 allows **one** probe per open-ended question. Both stop on `declined`.

The tool also has a `section` field: a string enum built per request by `section_labels_for()` (`Introduction`, then each distinct `questions.category` in `order_index` order, then `Closing`). Because the enum is dynamic, the tool dict is produced by `build_interview_tool(sections)` rather than a module constant, and `call_claude()` takes the labels as its third argument. `section` sits between `last_answer` and `message` in the schema (again deliberately — the model classifies where it is before it writes). The route stores the value on the assistant turn in `conversation_turns.section`, and the report page groups turns by it to render section headers.

The model's `section` claim is not trusted outright: it tends to transition one turn late at section boundaries, reporting the section it just left on the very turn that opens the next one. `routes/eval.py`'s `_section_for_asking_qid(conn, asking_qid)` overrides it — when `asking_question_id` names a real, active question, the stored section is that question's `category` straight from the DB, not whatever the model wrote. This only covers turns that pose a listed question; section openers that announce a topic without posing a question yet, plus probes and wrap-ups, still rely on the model getting `section` right, which is why the field's description is explicit that a section-opening message names the *new* section, not the one just finished.
