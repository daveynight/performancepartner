from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from database import get_db, fetchone, fetchall
from auth import require_user
from config import render

router = APIRouter()

REL_ORDER = ["self", "manager", "peer", "report"]
REL_COLORS = {
    "self":    {"border": "rgba(99,102,241,0.8)",  "bg": "rgba(99,102,241,0.15)"},
    "manager": {"border": "rgba(16,185,129,0.8)",  "bg": "rgba(16,185,129,0.15)"},
    "peer":    {"border": "rgba(245,158,11,0.8)",  "bg": "rgba(245,158,11,0.15)"},
    "report":  {"border": "rgba(239,68,68,0.8)",   "bg": "rgba(239,68,68,0.15)"},
}


@router.get("/reports/{cycle_id}/user/{user_id}")
async def user_report(cycle_id: int, user_id: int, request: Request):
    viewer = require_user(request)
    is_admin = viewer["role"] in ("admin", "manager")

    with get_db() as conn:
        cycle = fetchone(conn, "SELECT * FROM cycles WHERE id = ?", (cycle_id,))
        subject = fetchone(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
        if not cycle or not subject:
            return RedirectResponse("/dashboard", status_code=303)

        # Access control: staff can only see own report on closed cycles
        if not is_admin:
            if viewer["id"] != user_id or cycle["status"] != "closed":
                return RedirectResponse("/dashboard", status_code=303)

        # All completed assignments where this person was the subject
        assignments = fetchall(conn, """
            SELECT a.*, u.name AS evaluator_name
            FROM assignments a
            JOIN users u ON a.evaluator_id = u.id
            WHERE a.cycle_id = ? AND a.subject_id = ? AND a.status = 'completed'
            ORDER BY a.relationship
        """, (cycle_id, user_id))

        if not assignments:
            return render(request, "reports/no_data.html", {
                "cycle": cycle, "subject": subject,
            })

        # Counts per relationship
        rel_counts = {}
        for a in assignments:
            rel_counts[a["relationship"]] = rel_counts.get(a["relationship"], 0) + 1

        # --- Ratings aggregated by category × relationship ---
        cat_rel_rows = fetchall(conn, """
            SELECT q.category, a.relationship,
                   ROUND(AVG(r.rating), 2) AS avg_rating,
                   COUNT(r.rating) AS cnt
            FROM responses r
            JOIN assignments a ON r.assignment_id = a.id
            JOIN questions q ON r.question_id = q.id
            WHERE a.cycle_id = ? AND a.subject_id = ? AND a.status = 'completed'
              AND r.rating IS NOT NULL
            GROUP BY q.category, a.relationship
            ORDER BY q.category
        """, (cycle_id, user_id))

        # Ordered unique categories (preserve question order)
        cat_order = fetchall(conn, """
            SELECT DISTINCT q.category, MIN(q.order_index) AS min_order
            FROM responses r
            JOIN assignments a ON r.assignment_id = a.id
            JOIN questions q ON r.question_id = q.id
            WHERE a.cycle_id = ? AND a.subject_id = ? AND a.status = 'completed'
              AND r.rating IS NOT NULL
            GROUP BY q.category
            ORDER BY min_order
        """, (cycle_id, user_id))
        categories = [row["category"] for row in cat_order]

        # Radar data: (category, relationship) -> avg
        rating_lookup = {(r["category"], r["relationship"]): r["avg_rating"] for r in cat_rel_rows}

        radar_datasets = []
        for rel in REL_ORDER:
            data = [rating_lookup.get((cat, rel), None) for cat in categories]
            if any(v is not None for v in data):
                radar_datasets.append({
                    "label": rel.title(),
                    "data": [v if v is not None else 0 for v in data],
                    "borderColor": REL_COLORS[rel]["border"],
                    "backgroundColor": REL_COLORS[rel]["bg"],
                    "pointBackgroundColor": REL_COLORS[rel]["border"],
                    "pointRadius": 4,
                })

        # --- Per-question breakdown ---
        q_rows = fetchall(conn, """
            SELECT q.id, q.text, q.category, q.order_index,
                   a.relationship,
                   ROUND(AVG(r.rating), 2) AS avg_rating,
                   COUNT(r.rating) AS cnt
            FROM responses r
            JOIN assignments a ON r.assignment_id = a.id
            JOIN questions q ON r.question_id = q.id
            WHERE a.cycle_id = ? AND a.subject_id = ? AND a.status = 'completed'
              AND r.rating IS NOT NULL
            GROUP BY q.id, a.relationship
            ORDER BY q.order_index, a.relationship
        """, (cycle_id, user_id))

        # { category: [ {text, rels: {rel: avg}} ] }
        by_category: dict = {}
        q_index: dict = {}  # question text -> entry in by_category list
        for row in q_rows:
            cat = row["category"]
            if cat not in by_category:
                by_category[cat] = []
                q_index[cat] = {}
            if row["text"] not in q_index[cat]:
                entry = {"text": row["text"], "rels": {}}
                by_category[cat].append(entry)
                q_index[cat][row["text"]] = entry
            q_index[cat][row["text"]]["rels"][row["relationship"]] = row["avg_rating"]

        # --- Transcripts ---
        # Admin/manager see all; subject sees their own + others labeled by relationship
        transcripts = []
        for a in assignments:
            turns = fetchall(conn,
                "SELECT role, content FROM conversation_turns WHERE assignment_id = ? ORDER BY id",
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
                "turns": visible_turns,
            })

    return render(request, "reports/individual.html", {
        "cycle": cycle,
        "subject": subject,
        "rel_counts": rel_counts,
        "categories": categories,
        "radar_datasets": radar_datasets,
        "by_category": by_category,
        "rel_colors": REL_COLORS,
        "rel_order": REL_ORDER,
        "transcripts": transcripts,
        "is_admin": is_admin,
        "viewing_self": viewer["id"] == user_id,
    })
