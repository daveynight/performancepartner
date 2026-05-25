from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from database import get_db, fetchone, fetchall
from auth import require_user
from config import render
from interview import build_system_prompt, call_claude

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


def _load_turns(conn, assignment_id: int) -> list[dict]:
    return fetchall(conn,
        "SELECT role, content FROM conversation_turns WHERE assignment_id = ? ORDER BY id",
        (assignment_id,))


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
        turns = _load_turns(conn, assignment_id)

        saved_ratings = fetchall(conn,
            "SELECT question_id, rating FROM responses WHERE assignment_id = ? AND rating IS NOT NULL",
            (assignment_id,))
        rated_ids = {r["question_id"]: r["rating"] for r in saved_ratings}

    return render(request, "eval/chat.html", {
        "assignment": a,
        "evaluee": evaluee,
        "evaluator": evaluator,
        "turns": turns,
        "rated_ids": rated_ids,
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
                    existing = fetchone(conn,
                        "SELECT id FROM responses WHERE assignment_id = ? AND question_id = ?",
                        (assignment_id, q_id))
                    if existing:
                        conn.execute(
                            "UPDATE responses SET rating = ? WHERE assignment_id = ? AND question_id = ?",
                            (rating_val, assignment_id, q_id))
                    else:
                        conn.execute(
                            "INSERT INTO responses (assignment_id, question_id, rating) VALUES (?, ?, ?)",
                            (assignment_id, q_id, rating_val))
                    conn.commit()
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
            display_text, completed, rating_ids = call_claude(system_prompt, claude_messages)
        except Exception as e:
            return JSONResponse({"error": f"Claude error: {str(e)}"}, status_code=500)

        conn.execute(
            "INSERT INTO conversation_turns (assignment_id, role, content) VALUES (?, 'assistant', ?)",
            (assignment_id, display_text))

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
