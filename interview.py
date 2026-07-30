import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MODEL = "claude-haiku-4-5-20251001"

# The model is forced to answer every turn via this tool. Rating-button
# visibility is derived server-side from `asking_question_id` + the question's
# real type in the DB — never from a free-text marker the model must remember
# to print (that was the old, unreliable mechanism).
INTERVIEW_TOOL = {
    "name": "interview_turn",
    "description": "Return your next message to the evaluator for this turn.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
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
        "required": ["message", "asking_question_id", "interview_complete"],
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
- **If the value is 3 or lower**: acknowledge, then ask ONE follow-up to understand why
  (e.g. "That's a 2 — can you tell me a bit more about what's been challenging there?").
  Set `asking_question_id` to null on that follow-up turn. After their response (specific
  or not), move on. Never probe a second time on the same rating.
- NEVER ask the evaluator to verbalize or describe their rating instead of clicking — always wait
  for the `RATING:N:value` message.

---

## RULE 2 — Open-ended questions (question_type: text or goal)

- Ask as a warm, open-ended question. Leave `asking_question_id` null (these are not rating questions).
- If the answer is vague or generic (e.g. "fine", "good", "not sure", "they do okay"),
  ask ONE follow-up probe for a specific example or situation.
- If the second response is still vague, or the evaluator signals they have nothing more to add,
  accept it gracefully and move on. Never probe a third time.
- If the answer already names a project, event, behavior, or concrete outcome, it is specific
  enough — move on without probing.

---

## Section wrap-up (after all rating questions in a section)

Ask these two questions as plain open-ended questions — no rating buttons, `asking_question_id` null:
- "What did {evaluee_name} do particularly well in this area?"
- "Where could {evaluee_name} improve in this area?"

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


def call_claude(system_prompt: str, messages: list[dict]) -> tuple[str, bool, "int | None"]:
    """
    Returns (display_text, interview_complete, asking_question_id).

    The model is forced to answer via the `interview_turn` tool, so the three
    values come straight from validated tool input — no marker parsing.
    `asking_question_id` is the question the model says it is posing this turn
    (or None); the caller decides button visibility from the question's type.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
        tools=[INTERVIEW_TOOL],
        tool_choice={"type": "tool", "name": "interview_turn"},
    )
    block = next(b for b in response.content if b.type == "tool_use")
    data = block.input

    display = (data.get("message") or "").strip()
    completed = bool(data.get("interview_complete"))
    asking_qid = data.get("asking_question_id")

    return display, completed, asking_qid
