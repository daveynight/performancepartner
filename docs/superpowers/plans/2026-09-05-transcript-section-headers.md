# Transcript Section Headers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a header in each report-page transcript every time the interview moves into a new section (question category, Introduction, or Closing), so a human reader can see at a glance where in the interview they are.

**Architecture:** The interviewer model already answers every turn through a strict `interview_turn` tool call. We add a `section` enum field to that tool (enum built per request from the current question categories), persist it on each assistant turn in a new nullable `conversation_turns.section` column, and have the report route group turns by section so the template can emit a header row at each boundary. Demo transcripts are tagged the same way. Nothing infers sections from message text.

**Tech Stack:** Python 3.13, FastAPI + Starlette `TestClient`, Jinja2, raw SQLite via `database.py`, Anthropic SDK (`anthropic` 1.x, strict tool use), Tailwind CDN, pytest (new).

**Spec:** `docs/superpowers/specs/2026-09-05-transcript-section-headers-design.md`

## Global Constraints

- Headers appear on the **report transcript view only** (`templates/reports/individual.html`). The live chat page (`templates/eval/chat.html`) does not change.
- Section labels are exactly the `questions.category` strings in the DB, plus the two fixed labels `Introduction` and `Closing`. Do not invent other labels.
- In the tool schema, `section` MUST sit **after `last_answer` and before `message`**, and MUST be in `required`. Strict tool use generates fields in schema order; the classification must precede the prose.
- The `section` column is added by the same try/except `ALTER TABLE` pattern already used for `rating_question_id` in `database.py` — no migration framework, must stay idempotent.
- Turns with `section IS NULL` (pre-existing transcripts) must render exactly as they do today: no header.
- Follow existing patterns: raw SQL through `get_db()` / `fetchone()` / `fetchall()`, `require_user()` at the top of routes, no ORM, no new JS.
- Run every command from the worktree root: `/Users/night/3_projects/performancepartner/.claude/worktrees/transcript-section-headers`. Python is `.venv/bin/python`; pytest is `.venv/bin/pytest` once installed in Task 1.
- Commit after every task with a short imperative subject. Commit messages end with the line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- `CLAUDE.md` and `AGENTS.md` are near-identical mirrors (AGENTS.md swaps "Claude" for "Codex"). Every doc edit goes into both files.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `requirements-dev.txt` | Test-only dependencies | **Create** (pytest) |
| `tests/conftest.py` | Point the app at a temp DB before import; fixtures for a seeded DB, a logged-in client, and a ready assignment | **Create** |
| `tests/test_transcript_sections.py` | Unit tests for grouping turns by section | **Create** |
| `tests/test_interview_tool.py` | Unit tests for the dynamic tool schema and `call_claude` return value | **Create** |
| `tests/test_eval_section_storage.py` | Migration test + route test that the declared section is stored | **Create** |
| `tests/test_report_headers.py` | Route test that the report page renders headers in order | **Create** |
| `tests/test_seed_demo_sections.py` | `transcript_for()` emits `(role, content, section)` triples with the right labels | **Create** |
| `interview.py` | `section_labels_for()`, `build_interview_tool()`, prompt text, `call_claude()` 4-tuple | Modify |
| `database.py` | `ALTER TABLE conversation_turns ADD COLUMN section TEXT` migration | Modify (`~line 120-127`) |
| `routes/eval.py` | Pass labels into `call_claude`, store `section` on the assistant turn | Modify (lines 6, 150-164) |
| `routes/reports.py` | `group_turns_by_section()`; select `section`; pass `sections` per transcript | Modify (lines 125-148) |
| `templates/reports/individual.html` | Header row per section group | Modify (lines 136-152) |
| `seed_demo.py` | Tag demo turns with sections; write the column | Modify (`transcript_for`, insert loop ~709-713) |
| `CLAUDE.md`, `AGENTS.md` | Document the `section` field and column | Modify |

---

### Task 1: Test harness + `group_turns_by_section`

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_transcript_sections.py`
- Modify: `routes/reports.py` (add the helper below `REL_COLORS`, before the route)

**Interfaces:**
- Consumes: nothing new.
- Produces: `group_turns_by_section(turns: list[dict]) -> list[dict]` in `routes/reports.py`. Input dicts have keys `role`, `content`, and optionally `section` (str or None). Output is `[{"label": str | None, "turns": [turn, ...]}, ...]` in order. Tasks 4 and later depend on this exact shape. Also produces the pytest fixtures `db` and `client_with_assignment` used by Tasks 3 and 4.

- [ ] **Step 1: Add the dev requirements file and install**

Create `requirements-dev.txt`:

```
-r requirements.txt
pytest
```

Run:

```bash
.venv/bin/pip install -q -r requirements-dev.txt && .venv/bin/pytest --version
```

Expected: a `pytest 8.x` (or newer) version line.

- [ ] **Step 2: Create the test package and conftest**

Create an empty `tests/__init__.py`.

Create `tests/conftest.py`. The env vars MUST be set before any project module is imported, because `database.py` reads `DATABASE_PATH` at import time and `interview.py` constructs the Anthropic client at import time.

```python
"""Test fixtures.

Environment is configured at import time, before any project module loads:
`database.py` reads DATABASE_PATH when imported, and `interview.py` builds an
Anthropic client from ANTHROPIC_API_KEY when imported. `main.py` calls
load_dotenv(), which does not override variables that are already set.
"""
import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="pp-tests-")
os.environ["DATABASE_PATH"] = os.path.join(_TMP_DIR, "test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-never-used")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def db():
    """A fresh schema plus the seeded question bank, for one test."""
    from database import create_tables
    from seed import seed_questions

    path = os.environ["DATABASE_PATH"]
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    create_tables()
    seed_questions()
    yield path


@pytest.fixture
def client_with_assignment(db):
    """A running app with an admin, an evaluator (Eve), a subject (Sam), an
    active cycle, and one pending peer assignment Eve -> Sam.

    Yields (client, ids). Nobody is logged in yet; call login(client, email).
    """
    import main
    from auth import hash_password
    from database import get_db, fetchone

    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
            ("Test Admin", "admin@test.local", hash_password("pw"), "admin"))
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, department) VALUES (?,?,?,?,?)",
            ("Eve Evaluator", "eve@test.local", hash_password("pw"), "staff", "HMIS"))
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, department) VALUES (?,?,?,?,?)",
            ("Sam Subject", "sam@test.local", hash_password("pw"), "staff", "HMIS"))
        eve = fetchone(conn, "SELECT id FROM users WHERE email = 'eve@test.local'")["id"]
        sam = fetchone(conn, "SELECT id FROM users WHERE email = 'sam@test.local'")["id"]
        cur = conn.execute("INSERT INTO cycles (name, status) VALUES ('Test Cycle', 'active')")
        cycle_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO assignments (cycle_id, evaluator_id, subject_id, relationship, status) "
            "VALUES (?,?,?,?,?)",
            (cycle_id, eve, sam, "peer", "pending"))
        assignment_id = cur.lastrowid

    ids = {"assignment_id": assignment_id, "cycle_id": cycle_id,
           "evaluator_id": eve, "subject_id": sam}
    with TestClient(main.app) as client:  # runs startup hooks (all idempotent)
        yield client, ids


def login(client: TestClient, email: str, password: str = "pw") -> None:
    r = client.post("/login", data={"email": email, "password": password},
                    follow_redirects=False)
    assert r.status_code == 303, f"login failed for {email}: {r.status_code}"
```

- [ ] **Step 3: Write the failing tests for `group_turns_by_section`**

Create `tests/test_transcript_sections.py`:

```python
from routes.reports import group_turns_by_section


def _t(role, content, section=None):
    return {"role": role, "content": content, "section": section}


def test_assistant_turn_with_new_section_opens_a_group_and_user_turns_follow_it():
    turns = [
        _t("assistant", "Hi, welcome.", "Introduction"),
        _t("user", "Hello"),
        _t("assistant", "Let's talk about communication.", "Communication Skills"),
        _t("user", "Sure"),
        _t("assistant", "Anything concrete?", "Communication Skills"),
        _t("user", "She rewrote the packet."),
        _t("assistant", "Thanks, that's everything.", "Closing"),
    ]
    groups = group_turns_by_section(turns)
    assert [g["label"] for g in groups] == ["Introduction", "Communication Skills", "Closing"]
    assert [t["content"] for t in groups[1]["turns"]] == [
        "Let's talk about communication.", "Sure", "Anything concrete?", "She rewrote the packet."]
    assert groups[2]["turns"] == [turns[-1]]


def test_legacy_turns_without_sections_form_one_unlabeled_group():
    turns = [_t("assistant", "Hi"), _t("user", "Hello"), _t("assistant", "Bye")]
    groups = group_turns_by_section(turns)
    assert groups == [{"label": None, "turns": turns}]


def test_assistant_turn_with_null_section_stays_in_current_group():
    turns = [
        _t("assistant", "Let's talk about teamwork.", "Cooperation & Teamwork"),
        _t("user", "Ok"),
        _t("assistant", "Could you say more?"),  # section None mid-section
        _t("user", "He covered my shift."),
    ]
    groups = group_turns_by_section(turns)
    assert len(groups) == 1
    assert groups[0]["label"] == "Cooperation & Teamwork"
    assert len(groups[0]["turns"]) == 4


def test_repeated_same_section_does_not_open_a_new_group():
    turns = [
        _t("assistant", "Q1", "Communication Skills"),
        _t("user", "A1"),
        _t("assistant", "Q2", "Communication Skills"),
    ]
    assert len(group_turns_by_section(turns)) == 1


def test_user_turn_before_any_assistant_turn_lands_in_unlabeled_group():
    turns = [_t("user", "hello?"), _t("assistant", "Hi!", "Introduction")]
    groups = group_turns_by_section(turns)
    assert [g["label"] for g in groups] == [None, "Introduction"]


def test_missing_section_key_is_treated_as_none():
    turns = [{"role": "assistant", "content": "Hi"}, {"role": "user", "content": "Hey"}]
    assert group_turns_by_section(turns) == [{"label": None, "turns": turns}]


def test_empty_input_gives_empty_output():
    assert group_turns_by_section([]) == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_transcript_sections.py -v`

Expected: collection error, `ImportError: cannot import name 'group_turns_by_section' from 'routes.reports'`.

- [ ] **Step 5: Implement `group_turns_by_section`**

In `routes/reports.py`, directly after the `REL_COLORS = {...}` block and before `@router.get("/reports/{cycle_id}/user/{user_id}")`, add:

```python
def group_turns_by_section(turns: list[dict]) -> list[dict]:
    """Split an ordered transcript into consecutive section groups.

    An assistant turn whose `section` is set and differs from the current
    group's label opens a new group. User turns, and assistant turns with a
    null `section` (transcripts recorded before sections existed), stay in
    the current group. Legacy transcripts therefore come back as a single
    group with label None, which the template renders without a header.

    Returns [{"label": str | None, "turns": [turn, ...]}, ...].
    """
    groups: list[dict] = []
    for turn in turns:
        section = turn.get("section") if turn["role"] == "assistant" else None
        if not groups or (section is not None and section != groups[-1]["label"]):
            groups.append({"label": section, "turns": []})
        groups[-1]["turns"].append(turn)
    return groups
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_transcript_sections.py -v`

Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt tests/__init__.py tests/conftest.py tests/test_transcript_sections.py routes/reports.py
git commit -m "Add pytest harness and group_turns_by_section helper

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Dynamic `section` enum in the interview tool

**Files:**
- Modify: `interview.py` (lines 7-54 tool definition; lines 146-165 "How to respond" prompt block; lines 275-300 `call_claude`)
- Create: `tests/test_interview_tool.py`
- Modify: `CLAUDE.md` and `AGENTS.md` ("## AI model" section)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, all in `interview.py`:
  - `INTRO_SECTION = "Introduction"`, `CLOSING_SECTION = "Closing"` (module constants)
  - `section_labels_for(questions: list[dict]) -> list[str]` — `["Introduction", <distinct categories in order_index order>, "Closing"]`
  - `build_interview_tool(sections: list[str]) -> dict` — the strict tool dict with `section` enum = `sections`
  - `call_claude(system_prompt: str, messages: list[dict], sections: list[str]) -> tuple[str, bool, int | None, str | None]` — now returns `(display_text, completed, asking_question_id, section)`
  - The module constant `INTERVIEW_TOOL` is **removed** (only `call_claude` referenced it).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_tool.py`:

```python
import interview


def _q(qid, category, order_index):
    return {"id": qid, "category": category, "order_index": order_index,
            "question_type": "likert", "text": f"Q{qid}", "scope": "general"}


def test_section_labels_are_intro_then_categories_in_order_then_closing():
    questions = [
        _q(3, "Communication Skills", 201),
        _q(1, "Productivity & Technical Knowledge", 101),
        _q(2, "Productivity & Technical Knowledge", 102),
        _q(4, "Goals", 801),
    ]
    assert interview.section_labels_for(questions) == [
        "Introduction",
        "Productivity & Technical Knowledge",
        "Communication Skills",
        "Goals",
        "Closing",
    ]


def test_section_labels_with_no_questions_still_has_intro_and_closing():
    assert interview.section_labels_for([]) == ["Introduction", "Closing"]


def test_tool_has_section_enum_between_last_answer_and_message():
    tool = interview.build_interview_tool(["Introduction", "Communication Skills", "Closing"])
    props = tool["input_schema"]["properties"]
    assert list(props) == ["last_answer", "section", "message", "asking_question_id", "interview_complete"]
    assert props["section"]["type"] == "string"
    assert props["section"]["enum"] == ["Introduction", "Communication Skills", "Closing"]
    assert tool["input_schema"]["required"] == [
        "last_answer", "section", "message", "asking_question_id", "interview_complete"]
    assert tool["strict"] is True
    assert tool["input_schema"]["additionalProperties"] is False


def test_tool_keeps_existing_fields_unchanged():
    tool = interview.build_interview_tool(["Introduction", "Closing"])
    props = tool["input_schema"]["properties"]
    assert props["last_answer"]["enum"] == ["specific", "vague", "declined", "not_applicable"]
    assert props["asking_question_id"]["type"] == ["integer", "null"]
    assert props["interview_complete"]["type"] == "boolean"
    assert tool["name"] == "interview_turn"


class _FakeBlock:
    type = "tool_use"

    def __init__(self, tool_input):
        self.input = tool_input


class _FakeMessages:
    def __init__(self, tool_input):
        self._input = tool_input
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Resp", (), {"content": [_FakeBlock(self._input)]})()


class _FakeClient:
    def __init__(self, tool_input):
        self.messages = _FakeMessages(tool_input)


def test_call_claude_returns_section_and_sends_dynamic_enum(monkeypatch):
    fake = _FakeClient({
        "last_answer": "not_applicable",
        "section": "Communication Skills",
        "message": "  Let's talk about communication.  ",
        "asking_question_id": 7,
        "interview_complete": False,
    })
    monkeypatch.setattr(interview, "client", fake)
    sections = ["Introduction", "Communication Skills", "Closing"]

    result = interview.call_claude("sys", [{"role": "user", "content": "__START__"}], sections)

    assert result == ("Let's talk about communication.", False, 7, "Communication Skills")
    sent = fake.messages.calls[0]
    assert sent["tool_choice"] == {"type": "tool", "name": "interview_turn"}
    assert sent["tools"][0]["input_schema"]["properties"]["section"]["enum"] == sections


def test_call_claude_tolerates_missing_section(monkeypatch):
    fake = _FakeClient({"last_answer": "specific", "message": "Thanks!",
                        "asking_question_id": None, "interview_complete": True})
    monkeypatch.setattr(interview, "client", fake)
    assert interview.call_claude("sys", [], ["Introduction", "Closing"]) == ("Thanks!", True, None, None)


def test_prompt_explains_the_section_field():
    assignment = {"relationship": "manager"}
    evaluee = {"name": "Sam Subject", "department": None}
    evaluator = {"name": "Eve Evaluator"}
    prompt = interview.build_system_prompt(assignment, evaluee, evaluator, [])
    assert "`section`" in prompt
    assert "`Introduction`" in prompt
    assert "`Closing`" in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_interview_tool.py -v`

Expected: FAIL — `AttributeError: module 'interview' has no attribute 'section_labels_for'` (and similar for `build_interview_tool`; `call_claude` fails with a TypeError about the extra positional argument; the prompt test fails on the missing backticked `section`).

- [ ] **Step 3: Replace the `INTERVIEW_TOOL` constant with a builder**

In `interview.py`, replace everything from the comment at line 7 (`# The model is forced to answer every turn via this tool.`) through the closing `}` of `INTERVIEW_TOOL` at line 54 with:

```python
INTRO_SECTION = "Introduction"
CLOSING_SECTION = "Closing"


def section_labels_for(questions: list[dict]) -> list[str]:
    """Enum values for the tool's `section` field.

    "Introduction", then every distinct question category in order_index
    order, then "Closing". Built per request so admin edits to categories are
    picked up immediately and the model can only ever name a real section.
    """
    categories: list[str] = []
    for q in sorted(questions, key=lambda q: q["order_index"]):
        if q["category"] not in categories:
            categories.append(q["category"])
    return [INTRO_SECTION, *categories, CLOSING_SECTION]


# The model is forced to answer every turn via this tool. Rating-button
# visibility is derived server-side from `asking_question_id` + the question's
# real type in the DB — never from a free-text marker the model must remember
# to print (that was the old, unreliable mechanism). `section` is likewise a
# structured enum, built per request, so report transcripts can show section
# headers without parsing message text.
#
# Field order matters: strict tool use generates fields in schema order, so
# `last_answer` and `section` are classified BEFORE `message` is written.
def build_interview_tool(sections: list[str]) -> dict:
    return {
        "name": "interview_turn",
        "description": "Return your next message to the evaluator for this turn.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "last_answer": {
                    "type": "string",
                    "enum": ["specific", "vague", "declined", "not_applicable"],
                    "description": (
                        "Classify the evaluator's most recent message before writing `message`. "
                        "Use `specific` when it names a project, event, situation, behavior, or "
                        "concrete outcome. Use `vague` when it is short, generic, or evaluative "
                        "with no detail — e.g. 'good stuff', 'they're great', 'fine', 'pretty "
                        "good', 'they do okay'. Use `declined` when the evaluator signals they "
                        "have nothing further to offer — e.g. 'not much to add', 'that's all', "
                        "'I don't know', 'can't think of anything'. Use `not_applicable` only "
                        "when the last message was `__START__` or a `RATING:N:value`, or when "
                        "you have not yet asked an open-ended question."
                    ),
                },
                "section": {
                    "type": "string",
                    "enum": sections,
                    "description": (
                        "The part of the interview the evaluator is in AFTER this message. "
                        "Use `Introduction` for your greeting and any scoping questions. Once "
                        "you open a section, use that section's exact category name for its "
                        "opener, every listed question in it, your follow-up probes, and the "
                        "two wrap-up questions, until you open the next section. Use `Closing` "
                        "only for the final thank-you."
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "The conversational text to show the evaluator.",
                },
                "asking_question_id": {
                    "type": ["integer", "null"],
                    "description": (
                        "The numeric ID of the question from the list you are posing to the "
                        "evaluator in THIS message. Use null for introductions, follow-up "
                        "probes, section wrap-up questions, transitions, or anything that is "
                        "not directly posing one of the listed questions."
                    ),
                },
                "interview_complete": {
                    "type": "boolean",
                    "description": "true only when all sections and wrap-up questions are done.",
                },
            },
            "required": ["last_answer", "section", "message", "asking_question_id", "interview_complete"],
            "additionalProperties": False,
        },
    }
```

- [ ] **Step 4: Describe `section` in the system prompt**

In `build_system_prompt()`, inside the `## How to respond` block, the bullets currently read (around lines 152-161):

```
- `last_answer`: classify ...
- `asking_question_id`: when your `message` is posing ...
- `interview_complete`: false for every turn except your final thank-you.
```

Insert a new bullet between the `last_answer` bullet and the `asking_question_id` bullet:

```
- `section`: the part of the interview the evaluator is in after this message. Use
  `Introduction` while you are greeting them or asking scoping questions. Once you open
  a section, use that section's exact category heading (the `### ...` lines above) for
  its opener, its questions, your follow-up probes, and its two wrap-up questions, until
  you open the next section. Use `Closing` only on your final thank-you. Reports use
  this to put a heading over each part of the transcript, so keep it accurate.
```

Also extend the sentence that follows the bullets (currently "The system uses `asking_question_id` to decide when to show the evaluator the 1–5 rating buttons, ...") — leave it as is; the new bullet already explains the consumer of `section`.

- [ ] **Step 5: Update `call_claude` to take the labels and return the section**

Replace the whole `call_claude` function (currently lines 275-300) with:

```python
def call_claude(
    system_prompt: str, messages: list[dict], sections: list[str]
) -> tuple[str, bool, "int | None", "str | None"]:
    """
    Returns (display_text, interview_complete, asking_question_id, section).

    The model is forced to answer via the `interview_turn` tool, so all four
    values come straight from validated tool input — no marker parsing.
    `asking_question_id` is the question the model says it is posing this turn
    (or None); the caller decides button visibility from the question's type.
    `section` is one of `sections` (or None if absent) and is stored on the
    turn so report transcripts can show section headers.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
        tools=[build_interview_tool(sections)],
        tool_choice={"type": "tool", "name": "interview_turn"},
    )
    block = next(b for b in response.content if b.type == "tool_use")
    data = block.input

    display = (data.get("message") or "").strip()
    completed = bool(data.get("interview_complete"))
    asking_qid = data.get("asking_question_id")
    section = data.get("section")

    return display, completed, asking_qid, section
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_interview_tool.py -v`

Expected: 7 passed.

Also confirm nothing else still references the removed constant:

```bash
grep -rn "INTERVIEW_TOOL" --include='*.py' . | grep -v "/.venv/"
```

Expected: no output.

(The app's `routes/eval.py` still calls `call_claude` with two arguments at this point; Task 3 fixes that. Do not run a live interview between Task 2 and Task 3.)

- [ ] **Step 7: Document the field in CLAUDE.md and AGENTS.md**

In **both** `CLAUDE.md` and `AGENTS.md`, in the `## AI model` section:

1. In the first paragraph, change `call_claude()` returns `(display_text, completed, asking_question_id)` to `(display_text, completed, asking_question_id, section)`.
2. After the paragraph that begins `Probe caps differ by path:`, append a new paragraph:

```
The tool also has a `section` field: a string enum built per request by `section_labels_for()` (`Introduction`, then each distinct `questions.category` in `order_index` order, then `Closing`). Because the enum is dynamic, the tool dict is produced by `build_interview_tool(sections)` rather than a module constant, and `call_claude()` takes the labels as its third argument. `section` sits between `last_answer` and `message` in the schema (again deliberately — the model classifies where it is before it writes). The route stores the value on the assistant turn in `conversation_turns.section`, and the report page groups turns by it to render section headers. Nothing about button visibility or interview flow reads it.
```

- [ ] **Step 8: Commit**

```bash
git add interview.py tests/test_interview_tool.py CLAUDE.md AGENTS.md
git commit -m "Add dynamic section enum to the interview tool

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Persist the section on each assistant turn

**Files:**
- Modify: `database.py` (the migration block around lines 120-127)
- Modify: `routes/eval.py` (import at line 6; `call_claude` call at line 155; INSERT at lines 161-164)
- Create: `tests/test_eval_section_storage.py`
- Modify: `CLAUDE.md` and `AGENTS.md` (`## Schema` section and the eval-chat-flow bullet)

**Interfaces:**
- Consumes: `section_labels_for`, `call_claude` 4-tuple from Task 2; fixtures `client_with_assignment` and `login` from Task 1's `tests/conftest.py`.
- Produces: nullable `conversation_turns.section TEXT` column; every assistant turn written by `POST /eval/{id}/message` carries the model's declared section.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_section_storage.py`:

```python
import routes.eval as eval_routes
from database import create_tables, get_db, fetchone, fetchall
from tests.conftest import login


def test_conversation_turns_gains_section_column_and_migration_is_idempotent(db):
    create_tables()  # second run on an already-migrated DB must not raise
    with get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(conversation_turns)")}
    assert "section" in cols
    assert "rating_question_id" in cols  # existing migration still present


def test_message_route_stores_the_declared_section(client_with_assignment, monkeypatch):
    client, ids = client_with_assignment
    seen = {}

    def fake_call_claude(system_prompt, messages, sections):
        seen["sections"] = sections
        return "Hi Eve, thanks for making time.", False, None, "Introduction"

    monkeypatch.setattr(eval_routes, "call_claude", fake_call_claude)
    login(client, "eve@test.local")

    r = client.post(f"/eval/{ids['assignment_id']}/message", json={"message": "__START__"})

    assert r.status_code == 200
    assert r.json() == {"reply": "Hi Eve, thanks for making time.", "rating_ids": [], "completed": False}
    assert seen["sections"][0] == "Introduction"
    assert seen["sections"][-1] == "Closing"
    assert "Communication Skills" in seen["sections"]

    with get_db() as conn:
        turns = fetchall(conn,
            "SELECT role, content, section FROM conversation_turns WHERE assignment_id = ? ORDER BY id",
            (ids["assignment_id"],))
    assert turns == [
        {"role": "user", "content": "__START__", "section": None},
        {"role": "assistant", "content": "Hi Eve, thanks for making time.", "section": "Introduction"},
    ]


def test_message_route_stores_category_section_alongside_rating_id(client_with_assignment, monkeypatch):
    client, ids = client_with_assignment
    with get_db() as conn:
        qid = fetchone(conn,
            "SELECT id FROM questions WHERE category = 'Communication Skills' AND question_type = 'likert' "
            "ORDER BY order_index LIMIT 1")["id"]

    monkeypatch.setattr(eval_routes, "call_claude",
        lambda system_prompt, messages, sections:
            ("How clearly does Sam communicate?", False, qid, "Communication Skills"))
    login(client, "eve@test.local")

    r = client.post(f"/eval/{ids['assignment_id']}/message", json={"message": "Yes, same team."})

    assert r.status_code == 200
    assert r.json()["rating_ids"] == [qid]
    with get_db() as conn:
        row = fetchone(conn,
            "SELECT rating_question_id, section FROM conversation_turns "
            "WHERE assignment_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            (ids["assignment_id"],))
    assert row == {"rating_question_id": qid, "section": "Communication Skills"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_eval_section_storage.py -v`

Expected: the migration test fails with `assert 'section' in cols`; the two route tests fail with a 500 response (the route still unpacks three values from `call_claude` and the fake now needs three positional args).

- [ ] **Step 3: Add the migration**

In `database.py`, directly after the existing `rating_question_id` try/except (ends at the line `pass  # column already exists`), add:

```python
        # Same pattern: the interview section the model declared for an
        # assistant turn (a question category, "Introduction", or "Closing"),
        # so report transcripts can show section headers. NULL on turns
        # recorded before this column existed.
        try:
            conn.execute("ALTER TABLE conversation_turns ADD COLUMN section TEXT")
        except Exception:
            pass  # column already exists
```

- [ ] **Step 4: Wire the route**

In `routes/eval.py`:

Line 6, change the import to:

```python
from interview import build_system_prompt, call_claude, section_labels_for
```

Replace the `call_claude` call (inside the `try:` at line 155):

```python
            display_text, completed, asking_qid, section = call_claude(
                system_prompt, claude_messages, section_labels_for(questions))
```

Replace the assistant-turn INSERT (lines 161-164) with:

```python
        conn.execute(
            "INSERT INTO conversation_turns (assignment_id, role, content, rating_question_id, section) "
            "VALUES (?, 'assistant', ?, ?, ?)",
            (assignment_id, display_text, rating_ids[0] if rating_ids else None, section))
```

Do not change `_load_turns()` — the chat page and the Claude message history do not need the section.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_eval_section_storage.py -v`

Expected: 3 passed.

Run the full suite too: `.venv/bin/pytest -q` — expected all green (Task 1 + Task 2 + Task 3 tests).

- [ ] **Step 6: Document the column**

In **both** `CLAUDE.md` and `AGENTS.md`:

1. In `## Schema`, after the paragraph about `conversation_turns.rating_question_id`, add:

```
`conversation_turns.section` (nullable TEXT) records the interview section the model declared for an assistant turn — a `questions.category` string, `Introduction`, or `Closing`. Same migration pattern as `rating_question_id` (try/except `ALTER TABLE` in `create_tables()`, not in the `CREATE TABLE`). The report page groups a transcript's turns by it to render section headers; turns with NULL (recorded before the column existed) render without headers.
```

2. In the `**Eval chat flow**` bullet list (Architecture section), extend the bullet that begins `- \`POST /eval/{id}/message\` receives the user message` so its final clause reads `... stores the reply (with the model's declared \`section\`), and returns JSON \`{reply, rating_ids, completed}\``.

- [ ] **Step 7: Commit**

```bash
git add database.py routes/eval.py tests/test_eval_section_storage.py CLAUDE.md AGENTS.md
git commit -m "Store the declared interview section on each assistant turn

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Render section headers on the report page

**Files:**
- Modify: `routes/reports.py` (transcript block, lines 125-148)
- Modify: `templates/reports/individual.html` (turn loop, lines 136-152)
- Create: `tests/test_report_headers.py`

**Interfaces:**
- Consumes: `group_turns_by_section` (Task 1); `conversation_turns.section` (Task 3); fixtures from `tests/conftest.py`.
- Produces: each entry in the template's `transcripts` list now has `"sections": [{"label", "turns"}]` **instead of** `"turns"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_report_headers.py`:

```python
import re

from database import get_db
from tests.conftest import login


def _complete_with_turns(ids, turns):
    """Mark the fixture assignment completed and insert (role, content, section) turns."""
    with get_db() as conn:
        for role, content, section in turns:
            conn.execute(
                "INSERT INTO conversation_turns (assignment_id, role, content, section) VALUES (?,?,?,?)",
                (ids["assignment_id"], role, content, section))
        conn.execute("UPDATE assignments SET status = 'completed' WHERE id = ?", (ids["assignment_id"],))


def _report_html(client, ids):
    login(client, "admin@test.local")
    r = client.get(f"/reports/{ids['cycle_id']}/user/{ids['subject_id']}")
    assert r.status_code == 200
    return r.text


def test_report_shows_section_headers_in_order(client_with_assignment):
    client, ids = client_with_assignment
    _complete_with_turns(ids, [
        ("user", "__START__", None),
        ("assistant", "Hi Eve, thanks for making time.", "Introduction"),
        ("user", "Happy to help.", None),
        ("assistant", "Let's start with Communication Skills.", "Communication Skills"),
        ("user", "RATING:12:4", None),
        ("assistant", "What did Sam do particularly well here?", "Communication Skills"),
        ("user", "Sam rewrote the onboarding packet.", None),
        ("assistant", "That's everything — thank you.", "Closing"),
    ])
    html = _report_html(client, ids)

    headers = re.findall(r'data-section-header>\s*([^<]+?)\s*<', html)
    assert headers == ["Introduction", "Communication Skills", "Closing"]
    # The header sits after the intro turn and before the first turn of its section.
    comm_header = re.search(r'data-section-header>\s*Communication Skills', html).start()
    assert html.index("Hi Eve, thanks for making time.") < comm_header < html.index("particularly well here?")
    # Filtered turns stay filtered.
    assert "RATING:12:4" not in html
    assert "__START__" not in html


def test_report_without_sections_renders_no_headers(client_with_assignment):
    client, ids = client_with_assignment
    _complete_with_turns(ids, [
        ("assistant", "Hi Eve.", None),
        ("user", "Hello.", None),
        ("assistant", "Thanks, bye.", None),
    ])
    html = _report_html(client, ids)
    assert "data-section-header" not in html
    assert "Hi Eve." in html and "Thanks, bye." in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_report_headers.py -v`

Expected: `test_report_shows_section_headers_in_order` fails with `assert [] == ['Introduction', ...]`; `test_report_without_sections_renders_no_headers` passes already (that's fine — it guards the legacy path).

- [ ] **Step 3: Group turns in the route**

In `routes/reports.py`, replace the transcript block (from `transcripts = []` through the `transcripts.append({...})` call, lines 127-148) with:

```python
        transcripts = []
        for a in assignments:
            turns = fetchall(conn,
                "SELECT role, content, section FROM conversation_turns "
                "WHERE assignment_id = ? ORDER BY id",
                (a["id"],))
            # Filter out RATING: and __START__ messages
            visible_turns = [
                t for t in turns
                if t["content"] != "__START__" and not t["content"].startswith("RATING:")
            ]
            if not visible_turns:
                continue

            # Anonymize: peer/report evaluators shown as anonymous to non-admins
            show_name = is_admin or a["relationship"] in ("self", "manager")
            label = a["evaluator_name"] if show_name else a["relationship"].title()

            transcripts.append({
                "label": label,
                "relationship": a["relationship"],
                "sections": group_turns_by_section(visible_turns),
            })
```

- [ ] **Step 4: Render header rows in the template**

In `templates/reports/individual.html`, replace the inner turn loop (lines 137-151, from `{% for turn in t.turns %}` through its `{% endfor %}`) with:

```html
        {% for section in t.sections %}
        {% if section.label %}
        <div class="flex items-center gap-3 pt-2 {% if not loop.first %}mt-2 border-t border-gray-100{% endif %}">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-gray-500 whitespace-nowrap" data-section-header>
            {{ section.label }}
          </span>
          <span class="flex-1 h-px bg-gray-200"></span>
        </div>
        {% endif %}
        {% for turn in section.turns %}
        {% if turn.role == 'assistant' %}
        <div class="flex gap-3">
          <span class="text-xs font-medium text-indigo-500 w-16 flex-shrink-0 pt-0.5">Claude</span>
          <p class="text-sm text-gray-700 whitespace-pre-wrap">{{ turn.content }}</p>
        </div>
        {% else %}
        <div class="flex gap-3">
          <span class="text-xs font-medium text-gray-400 w-16 flex-shrink-0 pt-0.5">
            {% if t.relationship == 'self' %}You{% else %}Evaluator{% endif %}
          </span>
          <p class="text-sm text-gray-800 whitespace-pre-wrap">{{ turn.content }}</p>
        </div>
        {% endif %}
        {% endfor %}
        {% endfor %}
```

The turn markup is unchanged from today; only the outer section loop and the header row are new. The `data-section-header` attribute is what the test hooks on, and is harmless in the browser.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_report_headers.py -v`

Expected: 2 passed. Then `.venv/bin/pytest -q` — all green.

- [ ] **Step 6: Commit**

```bash
git add routes/reports.py templates/reports/individual.html tests/test_report_headers.py
git commit -m "Render interview section headers in report transcripts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Tag demo transcripts with sections

**Files:**
- Modify: `seed_demo.py` (`AREAS` block ~line 117; `transcript_for()` lines 504-603; insert loop lines 709-713)
- Create: `tests/test_seed_demo_sections.py`

**Interfaces:**
- Consumes: `conversation_turns.section` column (Task 3).
- Produces: `transcript_for(...)` now returns `list[tuple[str, str, str]]` — `(role, content, section)`; a new module constant `DEPT_CATEGORY = {"CES": "CES Program", "Finance": "Finance", "HMIS": "HMIS"}` mapping `users.department` to the dept-specific `questions.category`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_seed_demo_sections.py`:

```python
import seed_demo


def _sections(turns):
    return [s for _role, _content, s in turns]


def test_transcript_turns_are_role_content_section_triples():
    turns = seed_demo.transcript_for("aisha", "maria", "Maria Santos", "report", "HMIS")
    assert all(len(t) == 3 for t in turns)
    assert turns[0] == ("user", "__START__", "Introduction")
    assert turns[-1][0] == "assistant"
    assert turns[-1][2] == "Closing"


def test_every_area_the_relationship_unlocks_gets_its_category_label():
    turns = seed_demo.transcript_for("aisha", "maria", "Maria Santos", "manager", "HMIS")
    labels = _sections(turns)
    for _key, category, _scope in seed_demo.AREAS:
        assert category in labels, category
    assert "HMIS" in labels          # dept-specific block uses the real category name
    assert "Comments" in labels
    assert "Goals" in labels         # manager scope asks the goal questions


def test_peer_scoping_turns_are_in_introduction():
    turns = seed_demo.transcript_for("aisha", "tom", "Tom Reyes", "peer", "Finance")
    scoping = [t for t in turns if "scoping" in t[1].lower() or "peers" in t[1].lower()]
    assert scoping, "expected peer scoping turns"
    assert all(s == "Introduction" for _r, _c, s in scoping)
    assert "Goals" not in _sections(turns)  # peers never reach manager-scope questions
    assert "Finance" in _sections(turns)     # Tom's department block


def test_section_labels_change_only_on_assistant_turns():
    turns = seed_demo.transcript_for("aisha", "maria", "Maria Santos", "manager", "HMIS")
    for prev, cur in zip(turns, turns[1:]):
        if cur[2] != prev[2]:
            assert cur[0] == "assistant", f"section changed on a user turn: {cur}"
```

Note for the implementer: `"aisha"`, `"maria"`, `"tom"` are existing `PEOPLE` local keys in `seed_demo.py` (Maria Santos is the HMIS manager; Tom Reyes is Finance staff and the seeded low performer), and `PROFILE`, `CONTENT`, `SELF`, and `CLOSING` all have entries for them. `seed_demo.AREAS` is the existing list of `(key, category, scope)` tuples.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_seed_demo_sections.py -v`

Expected: FAIL with `ValueError: not enough values to unpack (expected 3, got 2)` or `assert all(len(t) == 3 ...)`.

- [ ] **Step 3: Add the department→category map**

In `seed_demo.py`, directly after the `AREAS = [...]` list, add:

```python
# users.department -> the dept-specific questions.category it maps to, so the
# transcript's section label matches what the live interviewer would declare.
DEPT_CATEGORY = {"CES": "CES Program", "Finance": "Finance", "HMIS": "HMIS"}
```

- [ ] **Step 4: Rewrite `transcript_for()` to emit triples**

Replace the body of `transcript_for()` so every appended tuple carries a section. Full replacement of the function (lines 504-603):

```python
def transcript_for(evaluator_local, subject_local, subject_name, relationship, subject_dept):
    """Build a full interview transcript mirroring the real question flow.

    Returns (role, content, section) triples. `section` is what the live
    interviewer would declare in the tool's `section` field: "Introduction",
    the exact questions.category label, or "Closing".

    Never emits '__START__' or 'RATING:' turns beyond the opening marker —
    reports filter those, and every Claude turn here has a real answer.
    """
    rng = random.Random(f"transcript:{evaluator_local}:{subject_local}:{relationship}")
    first = subject_name.split()[0]
    is_self = relationship == "self"
    # A struggling subject, judged by someone other than themselves.
    is_low = PROFILE.get(subject_local, 4) <= LOW_PERFORMER and not is_self
    scopes = SCOPES_FOR_REL[relationship]
    content = CONTENT[subject_local]

    turns = []
    section = "Introduction"

    def say(role, text):
        turns.append((role, text, section))

    say("user", "__START__")

    # --- Intro ---
    if is_self:
        say("assistant",
            f"Hi {first} — I'll be walking you through your self-evaluation for this cycle. "
            f"I'll ask about a few different areas, some as 1-5 ratings and some as open questions. "
            f"There are no wrong answers here; be as candid as you can. Let's get started.")
    else:
        say("assistant",
            f"Thanks for making time for this. I'll be gathering your feedback on {subject_name} for this "
            f"evaluation cycle. I'll ask about a few areas, some as 1-5 ratings and some as open questions. "
            f"Your specific examples are the most useful part, so share what comes to mind.")

    # --- Scoping (peers only, matching the real prompt) ---
    if relationship == "peer":
        say("assistant", f"First, a couple of quick scoping questions. Are you on {first}'s team — do you work with them directly day to day?")
        say("user", "Yes, we're both on Maria's team and we work together regularly.")
        say("assistant", f"Thanks. And are you {first}'s manager?")
        say("user", "No, we're peers.")
        say("assistant", "Perfect — that means I'll cover the general and team-specific questions with you.")

    # --- One section per category ---
    areas = [(k, label) for k, label, scope in AREAS if scope in scopes]
    if subject_dept in DEPT_CATEGORY:
        areas.append(("dept", DEPT_CATEGORY[subject_dept]))

    # Show the vague-answer follow-up probe in one section per transcript.
    probe_area = rng.choice([k for k, _ in areas]) if areas else None

    for key, label in areas:
        slot = content.get(key, {})
        if is_self:
            good, improve = SELF[subject_local].get(key, ("", ""))
        else:
            good = _pick(slot.get("good", []), rng)
            improve = _pick(slot.get("improve", []), rng)
        if not good and not improve:
            continue

        section = label
        say("assistant",
            f"Let's start with {label}." if key == areas[0][0]
            else rng.choice(SECTION_OPENERS).format(label=label))
        say("assistant",
            f"{rng.choice(AFTER_RATINGS)} What did {subject_name} do particularly well in this area?")

        if key == probe_area:
            # Demonstrates RULE 2: a vague answer gets one probe for specifics.
            # A struggling employee's evaluator hedges rather than praises.
            if is_low:
                say("user", rng.choice(VAGUE_NEUTRAL))
                say("assistant", PROBE_NEUTRAL)
            else:
                say("user", rng.choice(VAGUE_POSITIVE))
                say("assistant", PROBE_POSITIVE)
            say("user", good)
        else:
            say("user", good)

        say("assistant",
            f"{rng.choice(AFTER_STRENGTH)} And where could {subject_name} improve in this area?")
        say("user", improve)

    # --- Free-text Comments question (general scope) ---
    closing = CLOSING[subject_local]
    section = "Comments"
    say("assistant", f"Those are all the rated questions. Any additional comments you'd like to add about {subject_name}?")
    say("user", closing["comment"] if not is_self else
        "I'd say it was a solid cycle overall, with a couple of things I want to do differently next time.")

    # --- Manager-scope free text + goals ---
    if "manager" in scopes:
        say("assistant",
            f"Are there areas where {subject_name} could improve outcomes or personal growth — "
            f"including anything we've covered or beyond it?")
        say("user", closing["growth"])
        section = "Goals"
        say("assistant", f"What goals has {subject_name} been working on over the last 12 months?")
        say("user", closing["goal_past"])
        say("assistant", "And what goals should they focus on for the next 12 months?")
        say("user", closing["goal_next"])

    # --- Close ---
    section = "Closing"
    say("assistant",
        "That's everything — thank you for taking the time and for being so specific. "
        "Your responses have been recorded.")
    return turns
```

Notes on fidelity to the seeded question bank (`seed.py`): the "growth" question (order 702) is in category `Comments` with `manager_specific` scope, so it stays under `Comments`; the two goal questions (801/802) are category `Goals`. Keep those labels exactly as written.

- [ ] **Step 5: Write the column in the insert loop**

Replace the insert loop (lines 709-713) with:

```python
            for role, content, section in transcript_for(
                    id_to_local[ev], subj_local, subj_name, rel, subj_dept):
                conn.execute(
                    "INSERT INTO conversation_turns (assignment_id, role, content, section) "
                    "VALUES (?,?,?,?)",
                    (aid, role, content, section))
```

Also update the design-notes comment block near line 100-114 by appending one sentence to its last paragraph: `Every turn also carries the section label the live interviewer would declare, so demo reports show section headers.`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_seed_demo_sections.py -v`

Expected: 4 passed. Then `.venv/bin/pytest -q` — all green.

- [ ] **Step 7: Reseed the demo data and inspect**

```bash
.venv/bin/python seed_demo.py --wipe && .venv/bin/python seed_demo.py
.venv/bin/python - <<'EOF'
from database import get_db, fetchall
with get_db() as conn:
    print(fetchall(conn, "SELECT section, COUNT(*) AS n FROM conversation_turns GROUP BY section ORDER BY n DESC"))
EOF
```

Expected: a row per label (`Introduction`, each of the six area categories, `HMIS`/`Finance`/`CES Program`, `Comments`, `Goals`, `Closing`) and **no** `None` row.

(If the heredoc is refused by the harness, save the snippet to a file under `$CLAUDE_JOB_DIR/tmp` and run it with `PYTHONPATH=. .venv/bin/python <file>`.)

- [ ] **Step 8: Commit**

```bash
git add seed_demo.py tests/test_seed_demo_sections.py
git commit -m "Tag demo transcripts with interview sections

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end verification

**Files:** none modified (fix anything found, in the task where it belongs, with its own test and commit).

**Interfaces:** consumes everything above.

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/pytest -v`

Expected: every test in `tests/` passes (23 tests: 7 + 7 + 3 + 2 + 4).

- [ ] **Step 2: Migration idempotence against the pre-existing worktree DB**

The worktree's `performancepartner.db` was created before this branch. Start the server against it and confirm it boots and the column exists:

```bash
.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); import database; database.create_tables(); database.create_tables(); import sqlite3; c = sqlite3.connect(database.DATABASE_PATH); print([r[1] for r in c.execute('PRAGMA table_info(conversation_turns)')])"
```

Expected: the printed column list includes `section`, no exception.

- [ ] **Step 3: Demo report shows headers**

```bash
.venv/bin/uvicorn main:app --port 8001
```

Log in as `hmis@partnersincareoahu.org` / `changeme`, open the demo cycle (Admin → Cycles), then a subject's report (Aisha Patel is a good one — several evaluators). Expand each transcript. Check:

- Header rows appear: `Introduction`, then the category headers in interview order, then `Comments` (and `Goals` on manager/self transcripts), then `Closing`.
- The peer transcript's scoping exchange sits under `Introduction`.
- The dept-specific block header is the category name (`HMIS`, `Finance`, or `CES Program`), not "X-specific responsibilities".
- Headers are visually distinct from turns but quieter than the "Interview Transcripts" section title.

- [ ] **Step 4: Live interview writes sections**

Still on the server, log in as the demo-login user printed by `seed_demo.py` (the "Live-demo login" line) and run one pending evaluation for a few turns: intro, one rating click, one follow-up. Then inspect that assignment's turns (the most recently written assignment):

```bash
.venv/bin/python - <<'EOF'
from dotenv import load_dotenv; load_dotenv()
from database import get_db, fetchall, fetchone
with get_db() as conn:
    aid = fetchone(conn, "SELECT assignment_id FROM conversation_turns ORDER BY id DESC LIMIT 1")["assignment_id"]
    for t in fetchall(conn, "SELECT role, section, substr(content, 1, 60) AS snippet "
                            "FROM conversation_turns WHERE assignment_id = ? ORDER BY id", (aid,)):
        print(t)
EOF
```

(If the heredoc is refused by the harness, save the snippet to a file and run it with `.venv/bin/python <file>` from the worktree root.)

Expected: every assistant turn has a non-null `section`; the first is `Introduction`; after the opener the section is a real category name; rating buttons still appeared in the UI for the likert question (no regression in `asking_question_id`). If the model mis-labels a turn (e.g. still says `Introduction` on the first section opener), tighten the `section` description text in `build_interview_tool` and the prompt bullet in Task 2, rerun the tests, commit as a follow-up.

- [ ] **Step 5: Live chat page unchanged**

Reload the in-progress evaluation from Step 4 as the demo user: the chat page renders as before (no headers, pending rating buttons still reappear if the last turn was a likert question).

- [ ] **Step 6: Final commit state**

```bash
git status --short   # expected: clean
git log --oneline master..HEAD
```

Expected: the five feature commits above (plus the spec and plan commits) on `transcript-section-headers`. Hand off with the superpowers:finishing-a-development-branch skill.
