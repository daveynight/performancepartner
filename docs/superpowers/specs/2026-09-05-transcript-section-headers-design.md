# Transcript section headers

## Context

Interview transcripts on the report page (`templates/reports/individual.html`) are a flat list of Claude/Evaluator turns. A human reader can't tell at a glance which part of the interview they're in. We want a header each time the interview moves into a new section, where a section is a question **category** (Productivity & Technical Knowledge, Communication Skills, Cooperation & Teamwork, Comments, Goals, the dept-specific block, etc.), plus Introduction and Closing.

Scope decided with the user: report transcript view only (no live chat headers). There is no export/print/email of transcripts in the repo today, so there is nothing else to change.

## Why a stored per-turn label, not inference

Today the only structural signal on a turn is `conversation_turns.rating_question_id`, set only on unrated likert turns and never on demo data. Intros, probes, wrap-ups and transitions carry nothing. Inferring sections from that (or from message text) would mis-file transitions and wrap-ups and would be fragile against wording changes. The reliable move is the same one this codebase already made for rating buttons: have the model declare it in the tool call, validate it structurally, persist it.

## Design

### 1. Tool schema: add `section` (`interview.py`)
- Add a `section` field to `interview_turn`, placed right after `last_answer` and before `message` (strict tool use generates in schema order; classifying the section before writing the message is the point).
- `section` is a **string enum** built per request: `["Introduction"] + [distinct question categories passed to the prompt, in order_index order] + ["Closing"]`. Because the enum is dynamic, `INTERVIEW_TOOL` becomes `build_interview_tool(section_labels)`; `call_claude()` takes the tool (or labels) as a parameter and returns a 4-tuple `(display_text, completed, asking_qid, section)`.
- Description tells the model: the section the evaluator is in *after* this message. Intro + peer scoping → `Introduction`; section openers, questions, probes, wrap-ups → that category; final thank-you → `Closing`.
- Add a line to the "How to respond" block of the prompt describing `section`. Update the CLAUDE.md "AI model" section to document the new field.

### 2. Persist it (`database.py`, `routes/eval.py`)
- `ALTER TABLE conversation_turns ADD COLUMN section TEXT` inside the same try/except migration pattern as `rating_question_id` (`database.py:126`). Note in CLAUDE.md schema section that it's migration-only.
- `POST /eval/{id}/message` writes `section` on the assistant turn insert (`routes/eval.py:161-164`). User turns are not tagged; they inherit at render time (below).

### 3. Render headers (`routes/reports.py`, `templates/reports/individual.html`)
- New pure helper in `routes/reports.py`: `group_turns_by_section(turns) -> list[{"label": str|None, "turns": [...]}]`. Walks visible turns in order; an assistant turn with a non-null `section` different from the current group opens a new group; user turns (and assistant turns with null section, i.e. legacy data) stay in the current group. Legacy transcripts with no sections yield one group with `label=None`.
- Fetch `section` in the transcript SQL (`reports.py:130`) and pass `sections` instead of `turns` in each transcript dict.
- Template: loop groups; when `label` is set, emit a small header divider row (uppercase tracking-wide label with a hairline rule, matching the existing "Interview Transcripts" h2 styling at a smaller size) before that group's turns. Turn bubbles unchanged.

### 4. Demo data (`seed_demo.py`)
- `transcript_for()` returns `(role, content, section)` triples: intro/scoping → "Introduction"; each area block → its `label` (the AREAS labels already equal category text; dept block label stays as-is); comments → "Comments"; growth/goals → "Goals" (matching the seeded category names in `seed.py` — verify exact strings when implementing); close → "Closing".
- Insert loop (`seed_demo.py:709-713`) writes the `section` column.

### Out of scope (deliberately)
Live chat headers; scope-level (Team/Manager) grouping as a second header axis (category already distinguishes these in the seeded bank); backfilling pre-existing real transcripts (they simply render without headers); ratings summaries inside headers.

## Files touched
- `interview.py` — tool builder with dynamic enum, prompt text, `call_claude` return value
- `database.py` — migration
- `routes/eval.py` — store `section`
- `routes/reports.py` — `group_turns_by_section`, SQL, context
- `templates/reports/individual.html` — header rows
- `seed_demo.py` — tagged transcripts
- `CLAUDE.md` — document `section` field and column

## Verification
1. Unit tests (new `tests/` dir, add `pytest` to requirements — none exist today): `group_turns_by_section` on (a) a tagged sequence with user turns interleaved, (b) all-null legacy turns → single unlabeled group, (c) a null assistant turn mid-section stays in the current group; `build_interview_tool` produces the expected enum order and keeps `section` between `last_answer` and `message` in both `properties` order and `required`.
2. `python seed_demo.py` then open a demo subject's report as admin: every transcript shows Introduction → category headers → Comments/Goals → Closing, in the right places.
3. Run one real interview end-to-end against the dev server, then view its report: headers appear and match the flow; rating buttons still work (no regression in `asking_question_id`).
4. Restart the server against the existing DB to confirm the migration is idempotent.
