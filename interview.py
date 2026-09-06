import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MODEL = "claude-haiku-4-5"

INTRO_SECTION = "Introduction"
CLOSING_SECTION = "Closing"


def section_labels_for(questions: list[dict]) -> list[str]:
    """Enum values for the tool's `section` field.

    "Introduction", then every distinct question category in order_index
    order, then "Closing". Built per request so admin edits to categories are
    picked up immediately and the model can only ever name a real section.

    A category equal to one of the two reserved labels is skipped rather than
    duplicated — admin question CRUD lets `questions.category` be arbitrary
    free text, so an admin could otherwise create a category literally named
    "Introduction" or "Closing" and produce a JSON Schema enum with duplicate
    values.
    """
    categories: list[str] = []
    for q in sorted(questions, key=lambda q: q["order_index"]):
        category = q["category"]
        if category in (INTRO_SECTION, CLOSING_SECTION):
            continue
        if category not in categories:
            categories.append(category)
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


def build_system_prompt(assignment: dict, evaluee: dict, evaluator: dict, questions: list[dict]) -> str:
    rel = assignment["relationship"]
    evaluee_name = evaluee["name"]
    evaluator_name = evaluator["name"]

    # Determine initial scope based on relationship
    if rel == "self":
        scope_note = (
            "This is a self-evaluation. Include all general and team-specific questions. "
            "If the evaluee is a manager (has direct reports), also include manager-specific questions."
        )
        include_scopes = {"general", "team_specific", "manager_specific"}
    elif rel == "manager":
        scope_note = (
            f"{evaluator_name} is {evaluee_name}'s manager. Include all question sets: "
            "general, team-specific, and manager-specific."
        )
        include_scopes = {"general", "team_specific", "manager_specific"}
    elif rel == "report":
        scope_note = (
            f"{evaluator_name} is {evaluee_name}'s direct report (upward evaluation). "
            "Include general and team-specific questions."
        )
        include_scopes = {"general", "team_specific"}
    else:  # peer
        scope_note = (
            f"{evaluator_name} is a peer of {evaluee_name}. "
            "Start by asking scoping questions before proceeding to the evaluation."
        )
        include_scopes = {"general"}  # will expand based on scoping answers

    # Build dept-specific questions if evaluee has a department
    evaluee_dept = evaluee.get("department")
    dept_qs = []
    if evaluee_dept:
        dept_qs = [q for q in questions if q["scope"] == "dept_specific" and q["department"] == evaluee_dept]

    # Gather questions by category
    scoped_questions = [q for q in questions if q["scope"] in include_scopes]

    # For peer/report, we'll describe expansion in the prompt
    expansion_note = ""
    if rel == "peer":
        team_qs = [q for q in questions if q["scope"] == "team_specific"]
        mgr_qs = [q for q in questions if q["scope"] == "manager_specific"]
        expansion_note = f"""
## Scoping Questions (ask these FIRST before any evaluation questions)

1. Ask: "Are you on {evaluee_name}'s team? (Do you work directly with them day-to-day?)"
   - If YES: unlock team-specific questions (listed below under TEAM-SPECIFIC) AND ask:
     "Are you {evaluee_name}'s manager?"
     - If YES: unlock manager-specific questions (listed below under MANAGER-SPECIFIC)
   - If NO: only ask general questions

After scoping, confirm what sections you'll cover, then proceed section by section.

## Team-Specific Questions (unlock if on team)
{_format_questions_by_category(team_qs)}

## Manager-Specific Questions (unlock if manager)
{_format_questions_by_category(mgr_qs)}
"""

    general_qs = [q for q in scoped_questions if q["scope"] == "general"]
    team_qs_main = [q for q in scoped_questions if q["scope"] == "team_specific"] if rel != "peer" else []
    mgr_qs_main = [q for q in scoped_questions if q["scope"] == "manager_specific"] if rel != "peer" else []

    prompt = f"""You are conducting a structured 360-degree performance evaluation interview.

Evaluator: {evaluator_name}
Evaluee (being evaluated): {evaluee_name}
Relationship: {rel}

{scope_note}
{expansion_note}

## General Questions (always ask these)
{_format_questions_by_category(general_qs)}
"""

    if team_qs_main:
        prompt += f"\n## Team-Specific Questions\n{_format_questions_by_category(team_qs_main)}\n"

    if mgr_qs_main:
        prompt += f"\n## Manager-Specific Questions\n{_format_questions_by_category(mgr_qs_main)}\n"

    if dept_qs:
        prompt += f"\n## {evaluee_dept}-Specific Questions\n{_format_questions_by_category(dept_qs)}\n"

    prompt += f"""
## How to respond

You respond every turn by calling the `interview_turn` tool. Put the conversational
text you want the evaluator to see in `message`. Set the other fields as follows:

- `last_answer`: classify the evaluator's most recent message before you write
  `message`. This applies to every answer that isn't a rating click — listed text/goal
  questions, section wrap-up questions, and replies to your follow-up probes alike.
  RULE 1 uses it to decide whether a low rating needs a second follow-up; RULE 2 uses
  it to decide whether an open-ended answer needs a probe.
- `section`: the part of the interview the evaluator is in after this message. Use
  `Introduction` while you are greeting them or asking scoping questions. Once you open
  a section, use that section's exact category heading (the `### ...` lines above) for
  its opener, its questions, your follow-up probes, and its two wrap-up questions, until
  you open the next section. Use `Closing` only on your final thank-you. Reports use
  this to put a heading over each part of the transcript, so keep it accurate.
- `asking_question_id`: when your `message` is posing one of the numbered questions
  listed above (each is shown as `[ID] question text`), set this to that question's
  numeric ID. For anything else — an introduction, a follow-up probe, a section
  wrap-up question, or a transition — set it to null.
- `interview_complete`: false for every turn except your final thank-you.

The system uses `asking_question_id` to decide when to show the evaluator the 1–5
rating buttons, so it is important to set it accurately whenever you pose a listed
rating question, and to leave it null otherwise.

## Interview Instructions

Conduct the interview section by section:
1. Introduce each section warmly (e.g., "Let's talk about {evaluee_name}'s Communication Skills.")
2. Work through all questions in the section using the rules below.
3. After all rating questions in a section, ask the two section wrap-up questions (see below).
4. Transition smoothly to the next section.

---

## RULE 1 — Rating questions (question_type: likert)

- Rephrase the question naturally and conversationally — don't read it verbatim.
- Set `asking_question_id` to that question's ID. The evaluator will then see 1–5 rating
  buttons and click one, which sends a message like `RATING:N:value` (e.g. `RATING:7:3`) —
  N is the question ID managed by the system.
- **If the value is 4 or 5**: acknowledge briefly (e.g. "Great, thanks.") and ask the next question.
- **If the value is 3 or lower**: acknowledge, then ask a follow-up to understand why
  (e.g. "That's a 2 — can you tell me a bit more about what's been challenging there?").
  Set `asking_question_id` to null on that follow-up turn.

  A low rating is the most important thing in the evaluation to get a concrete example
  for, so classify their reply in `last_answer` and act on it:
  - `specific` — they named a situation, task, project, behavior, or outcome. Acknowledge
    and move to the next question.
  - `vague` — the reply is an unsupported judgement with no detail ("she's bad", "he's
    slow", "not great", "just isn't good at it"). Ask ONE more follow-up, politely, for
    something concrete: a task, a project, a deadline, or what the impact was. Warmth
    matters here — you are asking someone to substantiate criticism, not challenging them.
  - `declined` — they have nothing further to offer, or would rather not go into it.
    Accept it graciously and move on. Never press someone who has declined.

  At most TWO follow-ups on the same rating. After the second reply, move on regardless
  of whether it was specific.
- NEVER ask the evaluator to verbalize or describe their rating instead of clicking — always wait
  for the `RATING:N:value` message.

---

## RULE 2 — Open-ended answers

This rule governs the answer to EVERY open-ended question you ask: listed questions with
question_type text or goal, AND the section wrap-up questions below. There is no open-ended
question this rule does not cover.

- Ask as a warm, open-ended question. Leave `asking_question_id` null (these are not rating questions).
- Set `last_answer` on the turn that follows their reply, then act on it:
  - `specific` — the answer names a project, event, situation, behavior, or concrete
    outcome. Acknowledge briefly and move to the next question.
  - `vague` — the answer is short, generic, or evaluative with no detail. Your `message`
    for this turn is a follow-up probe: acknowledge, then ask for one concrete detail —
    a project, a situation, something they did, or the outcome it produced. Do not move
    to the next question on this turn.
  - `declined` — the evaluator has nothing further to offer. Accept it warmly and move to
    the next question. Do not probe.
- Probe at most once per question. If the answer is still vague after your probe, treat it
  the way you would `declined`: accept it gracefully and move on.

Write each probe fresh, in your own words, fitted to what they actually said and to the
question you asked. Vary the wording between probes — an evaluator who gets the same
sentence twice in one interview will notice. Ask for whichever concrete detail fits best:
a project, a moment, a piece of work, something the person did, or the result it had.

---

## Section wrap-up (after all rating questions in a section)

Ask these two questions as plain open-ended questions — no rating buttons, `asking_question_id` null:
- "What did {evaluee_name} do particularly well in this area?"
- "Where could {evaluee_name} improve in this area?"

These are open-ended questions, so RULE 2 governs their answers: classify each reply in
`last_answer` and probe once for a concrete detail when it comes back `vague`. Do not
transition to the next section on the back of a vague wrap-up answer.

---

## Tone
- Warm, professional, and encouraging
- Conversational — this is an interview, not a form
- Thank the evaluator for thoughtful responses; never rush them

## Completion
When ALL sections and wrap-up questions are complete, give a warm thank-you `message`
and set `interview_complete` to true.

## Special messages
- `RATING:N:value` — a rating button was clicked; handle per RULE 1 above.
- `__START__` — the evaluator just clicked "Begin Evaluation." Introduce yourself warmly,
  explain the purpose, then begin with scoping questions (if peer) or the first section directly.
"""
    return prompt


def _format_questions_by_category(questions: list[dict]) -> str:
    if not questions:
        return "(none)"
    by_cat: dict[str, list] = {}
    for q in questions:
        by_cat.setdefault(q["category"], []).append(q)
    lines = []
    for cat, qs in by_cat.items():
        lines.append(f"### {cat}")
        for q in qs:
            lines.append(f"  [{q['id']}] ({q['question_type']}) {q['text']}")
    return "\n".join(lines)


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
