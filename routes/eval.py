from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from database import get_db, fetchone, fetchall
from auth import require_user
from config import render
from interview import build_system_prompt, call_claude, section_labels_for

router = APIRouter()


def _get_assignment_or_403(conn, assignment_id: int, current_user: dict):
    a = fetchone(conn, "SELECT * FROM assignments WHERE id = ?", (assignment_id,))
    if not a:
        return None, "not_found"
    if a["evaluator_id"] != current_user["id"] and current_user["role"] not in ("admin", "manager"):
        return None, "forbidden"
    return a, None


def _load_questions(conn) -> list[dict]:
    return fetchall(conn,
        "SELECT * FROM questions WHERE is_active = 1 ORDER BY order_index",
        ())


def _is_rated(conn, assignment_id: int, question_id: int) -> bool:
    return fetchone(conn,
        "SELECT 1 FROM responses WHERE assignment_id=? AND question_id=? AND rating IS NOT NULL",
        (assignment_id, question_id)) is not None


def _upsert_rating(conn, assignment_id: int, question_id: int, value: int) -> None:
    """Write a rating, replacing any existing one for this question.

    Shared by the conversational path (a `RATING:` message on
    /eval/{id}/message) and the silent revision endpoint, so re-scoring a
    question updates its row instead of accumulating duplicates.
    """
    existing = fetchone(conn,
        "SELECT id FROM responses WHERE assignment_id = ? AND question_id = ?",
        (assignment_id, question_id))
    if existing:
        conn.execute(
            "UPDATE responses SET rating = ? WHERE assignment_id = ? AND question_id = ?",
            (value, assignment_id, question_id))
    else:
        conn.execute(
            "INSERT INTO responses (assignment_id, question_id, rating) VALUES (?, ?, ?)",
            (assignment_id, question_id, value))
    conn.commit()


def _section_for_asking_qid(conn, asking_qid):
    """The section a turn actually belongs to, derived from the DB rather than
    trusted from the model's `section` claim.

    The model transitions `section` one turn late at boundaries -- the turn
    that OPENS a new section by posing that section's first question is
    reported with the section it just left. When the model says it is posing
    question N, the DB knows N's real category, so that wins over whatever
    the model wrote in `section` -- the same principle CLAUDE.md documents
    for rating-button visibility in `_rating_ids_for`.

    Returns the question's category for an active question, or None if
    `asking_qid` is None, unknown, or inactive -- callers should fall back to
    the model's own `section` value in that case.
    """
    if asking_qid is None:
        return None
    q = fetchone(conn,
        "SELECT category FROM questions WHERE id=? AND is_active=1", (asking_qid,))
    return q["category"] if q else None


def _rating_ids_for(conn, assignment_id: int, asking_qid) -> list[int]:
    """Buttons show iff the model says it is posing question N AND the DB confirms
    N is an active likert question not yet rated. Deterministic, correctly scoped."""
    if asking_qid is None:
        return []
    q = fetchone(conn,
        "SELECT question_type FROM questions WHERE id=? AND is_active=1", (asking_qid,))
    if q and q["question_type"] == "likert" and not _is_rated(conn, assignment_id, asking_qid):
        return [asking_qid]
    return []


def _load_turns(conn, assignment_id: int) -> list[dict]:
    return fetchall(conn,
        "SELECT role, content FROM conversation_turns WHERE assignment_id = ? ORDER BY id",
        (assignment_id,))


def _chat_turns(conn, assignment_id: int) -> list[dict]:
    """Turns for the chat page, carrying the question each assistant turn posed.

    `_load_turns` stays as it is because its result is fed to the model as
    message history, where the extra column has no place.
    """
    return fetchall(conn,
        "SELECT role, content, rating_question_id FROM conversation_turns "
        "WHERE assignment_id = ? ORDER BY id",
        (assignment_id,))


def _revisable_ratings(conn, assignment_id: int) -> dict:
    """{question_id: rating} for scores the evaluator may still change.

    Only active likert questions that already carry a rating. The chat page
    re-renders a clickable row for each of these beneath the turn that posed
    it, so a score stays editable after a page reload instead of vanishing.
    """
    rows = fetchall(conn, """
        SELECT r.question_id, r.rating
        FROM responses r JOIN questions q ON r.question_id = q.id
        WHERE r.assignment_id = ? AND r.rating IS NOT NULL
          AND q.is_active = 1 AND q.question_type = 'likert'
    """, (assignment_id,))
    return {r["question_id"]: r["rating"] for r in rows}


@router.get("/eval/{assignment_id}")
async def eval_page(assignment_id: int, request: Request):
    user = require_user(request)
    with get_db() as conn:
        a, err = _get_assignment_or_403(conn, assignment_id, user)
        if err:
            return RedirectResponse("/dashboard", status_code=303)

        if a["status"] == "completed":
            evaluee = fetchone(conn, "SELECT * FROM users WHERE id = ?", (a["subject_id"],))
            return render(request, "eval/completed.html", {"assignment": a, "evaluee": evaluee})

        evaluee = fetchone(conn, "SELECT * FROM users WHERE id = ?", (a["subject_id"],))
        evaluator = fetchone(conn, "SELECT * FROM users WHERE id = ?", (a["evaluator_id"],))
        turns = _chat_turns(conn, assignment_id)
        revisable = _revisable_ratings(conn, assignment_id)

        saved_ratings = fetchall(conn,
            "SELECT question_id, rating FROM responses WHERE assignment_id = ? AND rating IS NOT NULL",
            (assignment_id,))
        rated_ids = {r["question_id"]: r["rating"] for r in saved_ratings}

        # Reload safety: if the most recent assistant turn posed a likert question
        # that isn't rated yet, re-render its 1-5 buttons on page load.
        pending_rating_id = None
        last_assistant = fetchone(conn,
            "SELECT rating_question_id FROM conversation_turns "
            "WHERE assignment_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            (assignment_id,))
        if last_assistant and last_assistant["rating_question_id"] is not None:
            qid = last_assistant["rating_question_id"]
            if not _is_rated(conn, assignment_id, qid):
                pending_rating_id = qid

    return render(request, "eval/chat.html", {
        "assignment": a,
        "evaluee": evaluee,
        "evaluator": evaluator,
        "turns": turns,
        "rated_ids": rated_ids,
        "revisable": revisable,
        "pending_rating_id": pending_rating_id,
        "fresh": len(turns) == 0,
    })


@router.post("/eval/{assignment_id}/message")
async def eval_message(assignment_id: int, request: Request):
    user = require_user(request)
    body = await request.json()
    user_content: str = body.get("message", "").strip()

    if not user_content:
        return JSONResponse({"error": "empty"}, status_code=400)

    with get_db() as conn:
        a, err = _get_assignment_or_403(conn, assignment_id, user)
        if err:
            return JSONResponse({"error": err}, status_code=403)

        if a["status"] == "completed":
            return JSONResponse({"error": "already_completed"}, status_code=400)

        evaluee = fetchone(conn, "SELECT * FROM users WHERE id = ?", (a["subject_id"],))
        evaluator = fetchone(conn, "SELECT * FROM users WHERE id = ?", (a["evaluator_id"],))
        questions = _load_questions(conn)

        # Handle rating intercept: store rating but still forward to Claude
        if user_content.startswith("RATING:"):
            parts = user_content.split(":")
            if len(parts) == 3:
                try:
                    q_id = int(parts[1])
                    rating_val = int(parts[2])
                    _upsert_rating(conn, assignment_id, q_id, rating_val)
                except (ValueError, IndexError):
                    pass

        # Mark in_progress on first message
        if a["status"] == "pending":
            conn.execute(
                "UPDATE assignments SET status='in_progress', started_at=datetime('now') WHERE id=?",
                (assignment_id,))
            conn.commit()

        # Store user turn
        conn.execute(
            "INSERT INTO conversation_turns (assignment_id, role, content) VALUES (?, 'user', ?)",
            (assignment_id, user_content))
        conn.commit()

        turns = _load_turns(conn, assignment_id)
        claude_messages = [{"role": t["role"], "content": t["content"]} for t in turns]
        system_prompt = build_system_prompt(a, evaluee, evaluator, questions)

        try:
            display_text, completed, asking_qid, section = call_claude(
                system_prompt, claude_messages, section_labels_for(questions))
        except Exception as e:
            return JSONResponse({"error": f"Claude error: {str(e)}"}, status_code=500)

        rating_ids = _rating_ids_for(conn, assignment_id, asking_qid)
        section = _section_for_asking_qid(conn, asking_qid) or section

        conn.execute(
            "INSERT INTO conversation_turns (assignment_id, role, content, rating_question_id, section) "
            "VALUES (?, 'assistant', ?, ?, ?)",
            (assignment_id, display_text, rating_ids[0] if rating_ids else None, section))

        if completed:
            conn.execute(
                "UPDATE assignments SET status='completed', completed_at=datetime('now') WHERE id=?",
                (assignment_id,))

        conn.commit()

    return JSONResponse({
        "reply": display_text,
        "rating_ids": rating_ids,
        "completed": completed,
    })


@router.post("/eval/{assignment_id}/rating")
async def eval_revise_rating(assignment_id: int, request: Request):
    """Change a score without involving the interviewer.

    The conversational path lives on POST /eval/{id}/message, which forwards a
    `RATING:` message to the model so it can acknowledge and probe. This
    endpoint is the quiet counterpart, for correcting a score the evaluator
    gave earlier in the interview: it writes `responses` and returns. No model
    call, and deliberately no `conversation_turns` row -- a reply about a
    question from two sections ago would land in the middle of an unrelated
    exchange.
    """
    user = require_user(request)
    body = await request.json()
    q_id = body.get("question_id")
    value = body.get("value")

    # bool is a subclass of int, so JSON `true` would otherwise score a 1.
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        return JSONResponse({"error": "value must be an integer 1-5"}, status_code=400)
    if isinstance(q_id, bool) or not isinstance(q_id, int):
        return JSONResponse({"error": "question_id must be an integer"}, status_code=400)

    with get_db() as conn:
        a, err = _get_assignment_or_403(conn, assignment_id, user)
        if err:
            return JSONResponse({"error": err}, status_code=403)

        if a["status"] == "completed":
            return JSONResponse({"error": "already_completed"}, status_code=400)

        q = fetchone(conn,
            "SELECT question_type FROM questions WHERE id = ? AND is_active = 1", (q_id,))
        if not q or q["question_type"] != "likert":
            return JSONResponse({"error": "not a scorable question"}, status_code=400)

        _upsert_rating(conn, assignment_id, q_id, value)

    return JSONResponse({"question_id": q_id, "value": value})
