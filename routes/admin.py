from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from auth import require_admin, hash_password
from config import render
from database import get_db, fetchone, fetchall

router = APIRouter(tags=["admin"])

DEPARTMENTS = ["CES", "Finance", "HMIS", "Planning", "LEP"]
ROLES = ["staff", "manager", "admin"]
SCOPES = ["general", "team_specific", "manager_specific", "dept_specific"]
QTYPES = ["likert", "text", "goal"]


@router.get("")
@router.get("/")
async def admin_root():
    return RedirectResponse("/admin/cycles", status_code=303)


# ── Users ─────────────────────────────────────────────────────────────────

@router.get("/users")
async def users_list(request: Request):
    require_admin(request)
    with get_db() as conn:
        users = fetchall(conn, """
            SELECT u.*, m.name AS manager_name
            FROM   users u
            LEFT JOIN users m ON m.id = u.manager_id
            ORDER  BY u.name
        """)
    return render(request, "admin/users.html", {"users": users, "active_tab": "users"})


@router.get("/users/new")
async def user_new_form(request: Request):
    require_admin(request)
    with get_db() as conn:
        managers = fetchall(conn, "SELECT id, name FROM users WHERE is_active=1 ORDER BY name")
    return render(request, "admin/user_form.html", {
        "form_user": {},
        "managers": managers,
        "departments": DEPARTMENTS,
        "roles": ROLES,
        "errors": {},
        "active_tab": "users",
    })


@router.post("/users/new")
async def user_new(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("staff"),
    department: str = Form(""),
    manager_id: str = Form(""),
):
    require_admin(request)
    errors = {}
    if not name.strip():     errors["name"] = "Name is required."
    if not email.strip():    errors["email"] = "Email is required."
    if not password:         errors["password"] = "Password is required."
    if role not in ROLES:    errors["role"] = "Invalid role."

    if not errors:
        with get_db() as conn:
            if fetchone(conn, "SELECT 1 FROM users WHERE lower(email)=?", (email.strip().lower(),)):
                errors["email"] = "An account with this email already exists."

    if errors:
        with get_db() as conn:
            managers = fetchall(conn, "SELECT id, name FROM users WHERE is_active=1 ORDER BY name")
        return render(request, "admin/user_form.html", {
            "form_user": {"name": name, "email": email, "role": role,
                          "department": department, "manager_id": manager_id},
            "managers": managers, "departments": DEPARTMENTS,
            "roles": ROLES, "errors": errors, "active_tab": "users",
        })

    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (name,email,password_hash,role,department,manager_id) VALUES (?,?,?,?,?,?)",
            (name.strip(), email.strip().lower(), hash_password(password),
             role, department or None, int(manager_id) if manager_id else None),
        )
    return RedirectResponse(f"/admin/users?success={name.strip()} added.", status_code=303)


@router.get("/users/{user_id}/edit")
async def user_edit_form(request: Request, user_id: int):
    require_admin(request)
    with get_db() as conn:
        form_user = fetchone(conn, "SELECT * FROM users WHERE id=?", (user_id,))
        managers  = fetchall(conn,
            "SELECT id, name FROM users WHERE is_active=1 AND id!=? ORDER BY name", (user_id,))
    if not form_user:
        return RedirectResponse("/admin/users?error=User not found.", status_code=303)
    return render(request, "admin/user_form.html", {
        "form_user": form_user, "managers": managers,
        "departments": DEPARTMENTS, "roles": ROLES,
        "errors": {}, "active_tab": "users",
    })


@router.post("/users/{user_id}/edit")
async def user_edit(
    request: Request,
    user_id: int,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    role: str = Form("staff"),
    department: str = Form(""),
    manager_id: str = Form(""),
    is_active: str = Form("1"),
):
    require_admin(request)
    errors = {}
    if not name.strip():  errors["name"] = "Name is required."
    if not email.strip(): errors["email"] = "Email is required."

    if not errors:
        with get_db() as conn:
            if fetchone(conn,
                "SELECT 1 FROM users WHERE lower(email)=? AND id!=?",
                (email.strip().lower(), user_id)):
                errors["email"] = "Another account already uses this email."

    if errors:
        with get_db() as conn:
            form_user = fetchone(conn, "SELECT * FROM users WHERE id=?", (user_id,))
            managers  = fetchall(conn,
                "SELECT id, name FROM users WHERE is_active=1 AND id!=? ORDER BY name", (user_id,))
        return render(request, "admin/user_form.html", {
            "form_user": {**form_user, "name": name, "email": email,
                          "role": role, "department": department, "manager_id": manager_id},
            "managers": managers, "departments": DEPARTMENTS,
            "roles": ROLES, "errors": errors, "active_tab": "users",
        })

    with get_db() as conn:
        if password:
            conn.execute(
                "UPDATE users SET name=?,email=?,password_hash=?,role=?,department=?,manager_id=?,is_active=? WHERE id=?",
                (name.strip(), email.strip().lower(), hash_password(password),
                 role, department or None, int(manager_id) if manager_id else None, int(is_active), user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET name=?,email=?,role=?,department=?,manager_id=?,is_active=? WHERE id=?",
                (name.strip(), email.strip().lower(),
                 role, department or None, int(manager_id) if manager_id else None, int(is_active), user_id),
            )
    return RedirectResponse(f"/admin/users?success={name.strip()} updated.", status_code=303)


# ── Questions ──────────────────────────────────────────────────────────────

@router.get("/questions")
async def questions_list(request: Request):
    require_admin(request)
    with get_db() as conn:
        questions = fetchall(conn, "SELECT * FROM questions ORDER BY order_index, category, text")
    return render(request, "admin/questions.html",
                  {"questions": questions, "active_tab": "questions"})


@router.get("/questions/new")
async def question_new_form(request: Request):
    require_admin(request)
    return render(request, "admin/question_form.html", {
        "form_q": {}, "departments": DEPARTMENTS,
        "scopes": SCOPES, "qtypes": QTYPES,
        "errors": {}, "active_tab": "questions",
    })


@router.post("/questions/new")
async def question_new(
    request: Request,
    category: str = Form(...),
    text: str = Form(...),
    question_type: str = Form("likert"),
    scope: str = Form("general"),
    department: str = Form(""),
    order_index: str = Form("0"),
):
    require_admin(request)
    errors = {}
    if not category.strip(): errors["category"] = "Category is required."
    if not text.strip():     errors["text"] = "Question text is required."

    if errors:
        return render(request, "admin/question_form.html", {
            "form_q": {"category": category, "text": text, "question_type": question_type,
                       "scope": scope, "department": department},
            "departments": DEPARTMENTS, "scopes": SCOPES, "qtypes": QTYPES,
            "errors": errors, "active_tab": "questions",
        })

    with get_db() as conn:
        conn.execute(
            "INSERT INTO questions (category,text,question_type,scope,department,order_index) VALUES (?,?,?,?,?,?)",
            (category.strip(), text.strip(), question_type, scope,
             department or None, int(order_index or 0)),
        )
    return RedirectResponse("/admin/questions?success=Question added.", status_code=303)


@router.get("/questions/{q_id}/edit")
async def question_edit_form(request: Request, q_id: int):
    require_admin(request)
    with get_db() as conn:
        form_q = fetchone(conn, "SELECT * FROM questions WHERE id=?", (q_id,))
    if not form_q:
        return RedirectResponse("/admin/questions?error=Question not found.", status_code=303)
    return render(request, "admin/question_form.html", {
        "form_q": form_q, "departments": DEPARTMENTS,
        "scopes": SCOPES, "qtypes": QTYPES,
        "errors": {}, "active_tab": "questions",
    })


@router.post("/questions/{q_id}/edit")
async def question_edit(
    request: Request,
    q_id: int,
    category: str = Form(...),
    text: str = Form(...),
    question_type: str = Form("likert"),
    scope: str = Form("general"),
    department: str = Form(""),
    order_index: str = Form("0"),
    is_active: str = Form("1"),
):
    require_admin(request)
    with get_db() as conn:
        conn.execute(
            "UPDATE questions SET category=?,text=?,question_type=?,scope=?,department=?,order_index=?,is_active=? WHERE id=?",
            (category.strip(), text.strip(), question_type, scope,
             department or None, int(order_index or 0), int(is_active), q_id),
        )
    return RedirectResponse("/admin/questions?success=Question updated.", status_code=303)


@router.post("/questions/{q_id}/toggle")
async def question_toggle(request: Request, q_id: int):
    require_admin(request)
    with get_db() as conn:
        q = fetchone(conn, "SELECT is_active FROM questions WHERE id=?", (q_id,))
        if q:
            conn.execute("UPDATE questions SET is_active=? WHERE id=?",
                         (0 if q["is_active"] else 1, q_id))
    return RedirectResponse("/admin/questions", status_code=303)


# ── Cycles ─────────────────────────────────────────────────────────────────

@router.get("/cycles")
async def cycles_list(request: Request):
    require_admin(request)
    with get_db() as conn:
        cycles = fetchall(conn, """
            SELECT c.*, u.name AS created_by_name,
                   (SELECT COUNT(*) FROM cycle_participants WHERE cycle_id=c.id) AS participant_count
            FROM   cycles c
            LEFT JOIN users u ON u.id = c.created_by
            ORDER  BY c.created_at DESC
        """)
    return render(request, "admin/cycles.html", {"cycles": cycles, "active_tab": "cycles"})


@router.get("/cycles/new")
async def cycle_new_form(request: Request):
    require_admin(request)
    with get_db() as conn:
        all_users = fetchall(conn,
            "SELECT id, name, department, role FROM users WHERE is_active=1 ORDER BY name")
    return render(request, "admin/cycle_form.html", {
        "cycle": {}, "all_users": all_users,
        "selected_ids": set(), "errors": {}, "active_tab": "cycles",
    })


@router.post("/cycles/new")
async def cycle_new(request: Request):
    admin = require_admin(request)
    form = await request.form()
    name          = form.get("name", "").strip()
    description   = form.get("description", "").strip()
    start_date    = form.get("start_date", "").strip()
    end_date      = form.get("end_date", "").strip()
    participant_ids = [int(v) for k, v in form.multi_items() if k == "participants"]

    errors = {}
    if not name: errors["name"] = "Name is required."

    if errors:
        with get_db() as conn:
            all_users = fetchall(conn,
                "SELECT id, name, department, role FROM users WHERE is_active=1 ORDER BY name")
        return render(request, "admin/cycle_form.html", {
            "cycle": {"name": name, "description": description,
                      "start_date": start_date, "end_date": end_date},
            "all_users": all_users, "selected_ids": set(participant_ids),
            "errors": errors, "active_tab": "cycles",
        })

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO cycles (name,description,start_date,end_date,created_by) VALUES (?,?,?,?,?)",
            (name, description or None, start_date or None, end_date or None, admin["id"]),
        )
        cycle_id = cur.lastrowid
        for uid in participant_ids:
            conn.execute(
                "INSERT OR IGNORE INTO cycle_participants (cycle_id,user_id) VALUES (?,?)",
                (cycle_id, uid))

    return RedirectResponse(f"/admin/cycles?success=Cycle+created.", status_code=303)


@router.get("/cycles/{cycle_id}/edit")
async def cycle_edit_form(request: Request, cycle_id: int):
    require_admin(request)
    with get_db() as conn:
        cycle = fetchone(conn, "SELECT * FROM cycles WHERE id=?", (cycle_id,))
        if not cycle or cycle["status"] == "closed":
            return RedirectResponse("/admin/cycles?error=Cycle+cannot+be+edited.", status_code=303)
        all_users = fetchall(conn,
            "SELECT id, name, department, role FROM users WHERE is_active=1 ORDER BY name")
        selected_ids = {r["user_id"] for r in
                        fetchall(conn, "SELECT user_id FROM cycle_participants WHERE cycle_id=?",
                                 (cycle_id,))}

        if cycle["status"] == "active":
            # Build participant list with completed-eval counts
            participants = fetchall(conn, """
                SELECT u.id, u.name, u.department,
                       (SELECT COUNT(*) FROM assignments a
                        WHERE a.cycle_id = ? AND a.status = 'completed'
                          AND (a.subject_id = u.id OR a.evaluator_id = u.id)) AS completed_count
                FROM cycle_participants cp
                JOIN users u ON u.id = cp.user_id
                WHERE cp.cycle_id = ?
                ORDER BY u.name
            """, (cycle_id, cycle_id))
            available_users = [u for u in all_users if u["id"] not in selected_ids]
        else:
            participants = []
            available_users = []

    return render(request, "admin/cycle_form.html", {
        "cycle": cycle,
        "all_users": all_users,
        "selected_ids": selected_ids,
        "participants": participants,
        "available_users": available_users,
        "errors": {},
        "active_tab": "cycles",
    })


@router.post("/cycles/{cycle_id}/edit")
async def cycle_edit(request: Request, cycle_id: int):
    require_admin(request)
    with get_db() as conn:
        cycle = fetchone(conn, "SELECT * FROM cycles WHERE id=?", (cycle_id,))
    if not cycle or cycle["status"] == "closed":
        return RedirectResponse("/admin/cycles?error=Cycle+cannot+be+edited.", status_code=303)

    form = await request.form()
    name        = form.get("name", "").strip()
    description = form.get("description", "").strip()
    start_date  = form.get("start_date", "").strip()
    end_date    = form.get("end_date", "").strip()

    errors = {}
    if not name:
        errors["name"] = "Name is required."

    if errors:
        with get_db() as conn:
            all_users = fetchall(conn,
                "SELECT id, name, department, role FROM users WHERE is_active=1 ORDER BY name")
            selected_ids = {r["user_id"] for r in
                            fetchall(conn, "SELECT user_id FROM cycle_participants WHERE cycle_id=?",
                                     (cycle_id,))}
            participants = []
            available_users = []
            if cycle["status"] == "active":
                participants = fetchall(conn, """
                    SELECT u.id, u.name, u.department,
                           (SELECT COUNT(*) FROM assignments a
                            WHERE a.cycle_id = ? AND a.status = 'completed'
                              AND (a.subject_id = u.id OR a.evaluator_id = u.id)) AS completed_count
                    FROM cycle_participants cp
                    JOIN users u ON u.id = cp.user_id
                    WHERE cp.cycle_id = ?
                    ORDER BY u.name
                """, (cycle_id, cycle_id))
                available_users = [u for u in all_users if u["id"] not in selected_ids]
        return render(request, "admin/cycle_form.html", {
            "cycle": {**cycle, "name": name}, "all_users": all_users,
            "selected_ids": selected_ids, "participants": participants,
            "available_users": available_users,
            "errors": errors, "active_tab": "cycles",
        })

    with get_db() as conn:
        conn.execute(
            "UPDATE cycles SET name=?,description=?,start_date=?,end_date=? WHERE id=?",
            (name, description or None, start_date or None, end_date or None, cycle_id),
        )
        # Draft cycles: also update participants from checkboxes
        if cycle["status"] == "draft":
            participant_ids = [int(v) for k, v in form.multi_items() if k == "participants"]
            conn.execute("DELETE FROM cycle_participants WHERE cycle_id=?", (cycle_id,))
            for uid in participant_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO cycle_participants (cycle_id,user_id) VALUES (?,?)",
                    (cycle_id, uid))

    return RedirectResponse(
        f"/admin/cycles/{cycle_id}/edit?success=Cycle+updated.", status_code=303)


@router.post("/cycles/{cycle_id}/participants/add")
async def participants_add(request: Request, cycle_id: int):
    require_admin(request)
    form = await request.form()
    new_ids = [int(v) for k, v in form.multi_items() if k == "user_id"]
    if not new_ids:
        return RedirectResponse(
            f"/admin/cycles/{cycle_id}/edit?error=No+users+selected.", status_code=303)

    with get_db() as conn:
        cycle = fetchone(conn, "SELECT * FROM cycles WHERE id=?", (cycle_id,))
        if not cycle or cycle["status"] != "active":
            return RedirectResponse("/admin/cycles?error=Cycle+not+active.", status_code=303)

        # Add new users to participants
        for uid in new_ids:
            conn.execute(
                "INSERT OR IGNORE INTO cycle_participants (cycle_id,user_id) VALUES (?,?)",
                (cycle_id, uid))

        # Fetch all participants (existing + new) with manager info
        all_participants = fetchall(conn, """
            SELECT u.id, u.manager_id FROM users u
            JOIN cycle_participants cp ON cp.user_id = u.id
            WHERE cp.cycle_id = ?
        """, (cycle_id,))
        manager_of = {p["id"]: p["manager_id"] for p in all_participants}
        existing_ids = {p["id"] for p in all_participants} - set(new_ids)

        rows = []
        for new_uid in new_ids:
            # Self-assessment for new user
            rows.append((cycle_id, new_uid, new_uid, "self"))
            # New user ↔ each existing participant
            for other_id in existing_ids:
                # new_uid evaluates other_id
                if manager_of.get(other_id) == new_uid:
                    rel = "manager"
                elif manager_of.get(new_uid) == other_id:
                    rel = "report"
                else:
                    rel = "peer"
                rows.append((cycle_id, new_uid, other_id, rel))

                # other_id evaluates new_uid
                if manager_of.get(new_uid) == other_id:
                    rel = "manager"
                elif manager_of.get(other_id) == new_uid:
                    rel = "report"
                else:
                    rel = "peer"
                rows.append((cycle_id, other_id, new_uid, rel))

            # New users evaluate each other (if multiple added at once)
            for other_new_id in new_ids:
                if other_new_id == new_uid:
                    continue
                if manager_of.get(other_new_id) == new_uid:
                    rel = "manager"
                elif manager_of.get(new_uid) == other_new_id:
                    rel = "report"
                else:
                    rel = "peer"
                rows.append((cycle_id, new_uid, other_new_id, rel))

        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO assignments "
                "(cycle_id, evaluator_id, subject_id, relationship) VALUES (?,?,?,?)",
                row)
        conn.commit()

    added = len(new_ids)
    return RedirectResponse(
        f"/admin/cycles/{cycle_id}/edit?success={added}+participant(s)+added.", status_code=303)


@router.post("/cycles/{cycle_id}/participants/remove")
async def participants_remove(request: Request, cycle_id: int):
    require_admin(request)
    form = await request.form()
    try:
        user_id = int(form.get("user_id", 0))
    except ValueError:
        user_id = 0

    if not user_id:
        return RedirectResponse(
            f"/admin/cycles/{cycle_id}/edit?error=Invalid+user.", status_code=303)

    with get_db() as conn:
        cycle = fetchone(conn, "SELECT * FROM cycles WHERE id=?", (cycle_id,))
        if not cycle or cycle["status"] != "active":
            return RedirectResponse("/admin/cycles?error=Cycle+not+active.", status_code=303)

        # Find all assignments involving this user
        assignment_ids = [
            r["id"] for r in fetchall(conn, """
                SELECT id FROM assignments
                WHERE cycle_id = ? AND (evaluator_id = ? OR subject_id = ?)
            """, (cycle_id, user_id, user_id))
        ]

        for aid in assignment_ids:
            conn.execute("DELETE FROM responses WHERE assignment_id=?", (aid,))
            conn.execute("DELETE FROM conversation_turns WHERE assignment_id=?", (aid,))
        if assignment_ids:
            conn.execute(
                f"DELETE FROM assignments WHERE id IN ({','.join('?' * len(assignment_ids))})",
                assignment_ids)

        conn.execute(
            "DELETE FROM cycle_participants WHERE cycle_id=? AND user_id=?",
            (cycle_id, user_id))
        conn.commit()

    return RedirectResponse(
        f"/admin/cycles/{cycle_id}/edit?success=Participant+removed.", status_code=303)


@router.post("/cycles/{cycle_id}/delete")
async def cycle_delete(request: Request, cycle_id: int):
    require_admin(request)
    with get_db() as conn:
        cycle = fetchone(conn, "SELECT status FROM cycles WHERE id=?", (cycle_id,))
        if cycle and cycle["status"] == "draft":
            conn.execute("DELETE FROM cycles WHERE id=?", (cycle_id,))
    return RedirectResponse("/admin/cycles?success=Cycle+deleted.", status_code=303)


@router.post("/cycles/{cycle_id}/activate")
async def cycle_activate(request: Request, cycle_id: int):
    require_admin(request)
    with get_db() as conn:
        cycle = fetchone(conn, "SELECT * FROM cycles WHERE id=?", (cycle_id,))
        if not cycle or cycle["status"] != "draft":
            return RedirectResponse("/admin/cycles?error=Only+draft+cycles+can+be+activated.", status_code=303)

        participants = fetchall(conn, """
            SELECT u.id, u.manager_id
            FROM   cycle_participants cp
            JOIN   users u ON u.id = cp.user_id
            WHERE  cp.cycle_id = ?
        """, (cycle_id,))

        if not participants:
            return RedirectResponse(
                f"/admin/cycles/{cycle_id}/edit?error=Add+participants+before+activating.",
                status_code=303)

        manager_of = {p["id"]: p["manager_id"] for p in participants}
        participant_ids = {p["id"] for p in participants}

        rows = []
        for p in participants:
            # Self-assessment
            rows.append((cycle_id, p["id"], p["id"], "self"))
            for other in participants:
                if other["id"] == p["id"]:
                    continue
                # p evaluates other — determine relationship
                if manager_of.get(other["id"]) == p["id"]:
                    rel = "manager"   # p is other's manager
                elif manager_of.get(p["id"]) == other["id"]:
                    rel = "report"    # other is p's manager → upward feedback
                else:
                    rel = "peer"
                rows.append((cycle_id, p["id"], other["id"], rel))

        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO assignments "
                "(cycle_id, evaluator_id, subject_id, relationship) VALUES (?,?,?,?)",
                row,
            )
        conn.execute("UPDATE cycles SET status='active' WHERE id=?", (cycle_id,))

    total = len(rows)
    return RedirectResponse(
        f"/admin/cycles/{cycle_id}/progress?success={total}+evaluations+generated.+Cycle+is+now+active.",
        status_code=303,
    )


@router.post("/cycles/{cycle_id}/close")
async def cycle_close(request: Request, cycle_id: int):
    require_admin(request)
    with get_db() as conn:
        conn.execute(
            "UPDATE cycles SET status='closed' WHERE id=? AND status='active'", (cycle_id,))
    return RedirectResponse("/admin/cycles?success=Cycle+closed.", status_code=303)


@router.get("/cycles/{cycle_id}/progress")
async def cycle_progress(request: Request, cycle_id: int):
    require_admin(request)
    with get_db() as conn:
        cycle = fetchone(conn, "SELECT * FROM cycles WHERE id=?", (cycle_id,))
        if not cycle:
            return RedirectResponse("/admin/cycles?error=Cycle+not+found.", status_code=303)
        assignments = fetchall(conn, """
            SELECT a.id, a.relationship, a.status,
                   a.subject_id,
                   ev.name AS evaluator_name,
                   su.name AS subject_name
            FROM   assignments a
            JOIN   users ev ON ev.id = a.evaluator_id
            JOIN   users su ON su.id = a.subject_id
            WHERE  a.cycle_id = ?
            ORDER  BY su.name, ev.name
        """, (cycle_id,))
        participants = fetchall(conn, """
            SELECT u.id, u.name FROM cycle_participants cp
            JOIN users u ON u.id = cp.user_id
            WHERE cp.cycle_id = ? ORDER BY u.name
        """, (cycle_id,))
        total     = len(assignments)
        completed = sum(1 for a in assignments if a["status"] == "completed")
    return render(request, "admin/cycle_progress.html", {
        "cycle": cycle,
        "assignments": assignments,
        "participants": participants,
        "total": total,
        "completed": completed,
        "active_tab": "cycles",
    })
