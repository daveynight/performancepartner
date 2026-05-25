from fastapi import APIRouter, Request

from auth import require_user
from config import render
from database import get_db, fetchall

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(request: Request):
    user = require_user(request)

    with get_db() as conn:
        pending = fetchall(conn, """
            SELECT a.id, a.relationship, a.status,
                   s.name  AS subject_name,
                   c.name  AS cycle_name,
                   c.end_date
            FROM   assignments a
            JOIN   users  s ON s.id = a.subject_id
            JOIN   cycles c ON c.id = a.cycle_id
            WHERE  a.evaluator_id = ?
              AND  a.status IN ('pending','in_progress')
              AND  c.status = 'active'
            ORDER  BY c.end_date, s.name
        """, (user["id"],))

        completed = fetchall(conn, """
            SELECT a.id, a.relationship, a.completed_at,
                   s.name  AS subject_name,
                   c.name  AS cycle_name
            FROM   assignments a
            JOIN   users  s ON s.id = a.subject_id
            JOIN   cycles c ON c.id = a.cycle_id
            WHERE  a.evaluator_id = ?
              AND  a.status = 'completed'
            ORDER  BY a.completed_at DESC
            LIMIT  10
        """, (user["id"],))

        # Closed cycles where user has a completed self-evaluation → can view own report
        my_reports = fetchall(conn, """
            SELECT c.id AS cycle_id, c.name AS cycle_name
            FROM   assignments a
            JOIN   cycles c ON c.id = a.cycle_id
            WHERE  a.evaluator_id = ? AND a.subject_id = ?
              AND  a.relationship = 'self'
              AND  a.status = 'completed'
              AND  c.status = 'closed'
            ORDER  BY c.end_date DESC
        """, (user["id"], user["id"]))

    return render(request, "dashboard.html", {
        "pending": pending,
        "completed": completed,
        "my_reports": my_reports,
    })
