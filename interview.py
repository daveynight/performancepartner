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

Conduct the interview section by section. For each section:
1. Introduce the section warmly (e.g., "Let's talk about {evaluee_name}'s Communication Skills.")
2. For each Likert question in the section:
   - Ask it conversationally (rephrase naturally, don't read it robotically)
   - End your message with exactly: [SHOW_RATINGS:{{question_id}}]
   - Wait for the rating response before moving on
3. After all ratings in a section, ask:
   - "What did {evaluee_name} do particularly well in this area?"
   - "Where could {evaluee_name} improve?"
4. Transition smoothly to the next section.

For text/comment questions (question_type = "text"): Ask them as open-ended questions without rating buttons.
For goal questions (question_type = "goal"): Ask them as open-ended questions, one at a time.

## Probing for specifics — IMPORTANT

After ANY open-ended text response (the "did well", "could improve", comment questions, goal questions):
- If the answer is vague, short, or generic — e.g., "really well", "they do fine", "could be better",
  "not really", "yes", "good", "hard to say" — you MUST ask a follow-up probe before moving on.
- A good probe asks for a concrete example or situation:
  e.g., "That's helpful — can you think of a specific situation where you saw that?"
  or "Can you give me an example of what that looks like day-to-day?"
- Ask the probe only ONCE. If the second answer is still vague or the evaluator says they can't
  think of an example, accept it gracefully and move on. Never ask the same probe a third time.
- A response counts as specific enough if it names a project, event, behavior, or concrete outcome.
  If it does, move on without probing.

## Tone
- Warm, professional, and encouraging
- Keep it conversational — this is an interview, not a form
- Never rush the evaluator; thank them for thoughtful responses
- If they give a rating, acknowledge it briefly before moving on

## Completion
When ALL sections are complete and you've collected all required ratings and responses, say a warm
thank-you and end your final message with exactly: [INTERVIEW_COMPLETE]

## Rating Messages
When the evaluator clicks a rating button, you will receive a message like:
  RATING:{{question_id}}:{{value}}
Acknowledge the rating briefly (e.g., "Got it, a 4 — thanks.") and continue with the next question.

When you receive the message "__START__", that means the evaluator just clicked "Begin Evaluation."
Respond by introducing yourself warmly, explaining the purpose, and starting with scoping questions
(if peer) or directly with the first section's introduction and first question.
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
            lines.append(f"  - [ID:{q['id']}] [{q['question_type']}] {q['text']}")
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
