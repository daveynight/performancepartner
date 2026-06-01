import os
import re
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MODEL = "claude-haiku-4-5-20251001"


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
## Interview Instructions

Conduct the interview section by section:
1. Introduce each section warmly (e.g., "Let's talk about {evaluee_name}'s Communication Skills.")
2. Work through all questions in the section using the rules below.
3. After all SHOW_RATINGS questions in a section, ask the two section wrap-up questions (see below).
4. Transition smoothly to the next section.

---

## RULE 1 — Questions prefixed → SHOW_RATINGS:N (rating questions)

- Rephrase the question naturally and conversationally — don't read it verbatim.
- Your message MUST end with exactly `[SHOW_RATINGS:N]` where N is the number in the prefix.
  Example: if the prefix is `→ SHOW_RATINGS:7`, end your message with `[SHOW_RATINGS:7]`.
- The evaluator will respond with a message like `RATING:N:value` (e.g. `RATING:7:3`).
- **If the value is 4 or 5**: acknowledge briefly (e.g. "Great, thanks.") and ask the next question.
- **If the value is 3 or lower**: acknowledge, then ask ONE follow-up to understand why
  (e.g. "That's a 2 — can you tell me a bit more about what's been challenging there?").
  After their response (specific or not), move on. Never probe a second time on the same rating.
- NEVER ask the evaluator to verbalize or describe their rating instead of clicking — always wait
  for the `RATING:N:value` message.
- NEVER emit `[SHOW_RATINGS:N]` for any question that is not prefixed → SHOW_RATINGS.

---

## RULE 2 — Questions prefixed → OPEN_TEXT:N or → OPEN_GOAL:N (open-ended questions)

- Ask as a warm, open-ended question. Do NOT include `[SHOW_RATINGS:N]` in your message.
- If the answer is vague or generic (e.g. "fine", "good", "not sure", "they do okay"),
  ask ONE follow-up probe for a specific example or situation.
- If the second response is still vague, or the evaluator signals they have nothing more to add,
  accept it gracefully and move on. Never probe a third time.
- If the answer already names a project, event, behavior, or concrete outcome, it is specific
  enough — move on without probing.

---

## Section wrap-up (after all SHOW_RATINGS questions in a section)

Ask these two questions as plain open-ended questions — no rating buttons, follow RULE 2:
- "What did {evaluee_name} do particularly well in this area?"
- "Where could {evaluee_name} improve in this area?"

---

## Tone
- Warm, professional, and encouraging
- Conversational — this is an interview, not a form
- Thank the evaluator for thoughtful responses; never rush them

## Completion
When ALL sections and wrap-up questions are complete, say a warm thank-you and end your
final message with exactly: [INTERVIEW_COMPLETE]

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
            if q["question_type"] == "likert":
                prefix = f"→ SHOW_RATINGS:{q['id']}"
            elif q["question_type"] == "goal":
                prefix = f"→ OPEN_GOAL:{q['id']}"
            else:
                prefix = f"→ OPEN_TEXT:{q['id']}"
            lines.append(f"  {prefix:<22} {q['text']}")
    return "\n".join(lines)


def call_claude(system_prompt: str, messages: list[dict]) -> tuple[str, bool, list[int]]:
    """
    Returns (display_text, interview_complete, question_ids_to_show_ratings_for)
    display_text has markers stripped.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    raw = response.content[0].text

    completed = "[INTERVIEW_COMPLETE]" in raw

    rating_ids: list[int] = []
    for match in re.finditer(r"\[SHOW_RATINGS:(\d+)\]", raw):
        rating_ids.append(int(match.group(1)))

    # Strip markers from displayed text
    display = re.sub(r"\[SHOW_RATINGS:\d+\]", "", raw)
    display = display.replace("[INTERVIEW_COMPLETE]", "").strip()

    return display, completed, rating_ids
