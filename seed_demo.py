"""Seed a demo evaluation cycle for demonstrations.

Usage:
    python seed_demo.py          # create demo users + an active cycle (idempotent)
    python seed_demo.py --wipe   # remove ALL demo data created by this script

Safe to run against production: it only touches the demo users (all on the
@example.com domain) and the single named demo cycle. It never modifies real
users/cycles, and the app's startup seeders are unaffected.

What it creates:
  * 5 demo users (org chart: one manager + four reports), password "demo1234"
  * one ACTIVE cycle with all N x N assignments (same algorithm as the
    "Activate" button in the admin UI)
  * every evaluation EXCEPT the demo-login user's is pre-filled as `completed`
    with 1-5 ratings + short transcripts, so dashboards/reports look real
  * the demo-login user's (James Chen) assignments stay `pending` so you can
    log in as that user and run a live AI interview in front of an audience
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import random

from dotenv import load_dotenv
load_dotenv()

from database import get_db, fetchone, fetchall
from auth import hash_password
from seed import seed_questions

DEMO_DOMAIN = "example.com"
DEMO_PASSWORD = "demo1234"
CYCLE_NAME = "Q3 2026 Performance Review (Demo)"
ADMIN_EMAIL = "hmis@partnersincareoahu.org"

# The demo user whose outgoing evaluations stay PENDING (for a live demo).
DEMO_LOGIN = "james"

# name, email-local, role, department, manager (email-local or None)
PEOPLE = [
    ("Maria Santos",   "maria",   "manager", "HMIS",     None),
    ("James Chen",     "james",   "staff",   "HMIS",     "maria"),
    ("Aisha Patel",    "aisha",   "staff",   "CES",      "maria"),
    ("Tom Reyes",      "tom",     "staff",   "Finance",  "maria"),
    ("Leilani Kahale", "leilani", "staff",   "Planning", "maria"),
]

# Slight per-person profile so radar charts aren't flat (higher = stronger).
PROFILE = {"maria": 5, "james": 4, "aisha": 5, "tom": 4, "leilani": 4}


def email_for(local: str) -> str:
    return f"{local}@{DEMO_DOMAIN}"


def rel_of(evaluator_id, subject_id, manager_of):
    """Same relationship logic as routes/admin.py cycle_activate."""
    if evaluator_id == subject_id:
        return "self"
    if manager_of.get(subject_id) == evaluator_id:
        return "manager"   # evaluator is the subject's manager
    if manager_of.get(evaluator_id) == subject_id:
        return "report"    # subject is the evaluator's manager (upward feedback)
    return "peer"


def rating_for(evaluator_local, subject_local, qid):
    """Deterministic, believable rating weighted toward the subject's profile."""
    rng = random.Random(f"{evaluator_local}:{subject_local}:{qid}")
    base = PROFILE.get(subject_local, 4)
    if base >= 5:
        return rng.choices([3, 4, 5], weights=[1, 3, 6])[0]
    return rng.choices([3, 4, 5], weights=[2, 5, 3])[0]


def transcript_for(subject_name, relationship):
    """A few plausible turns (never '__START__' or 'RATING:' — those are filtered)."""
    first = subject_name.split()[0]
    if relationship == "self":
        return [
            ("assistant", f"To start, how do you feel your performance went this cycle, {first}?"),
            ("user", "Overall a strong cycle. I hit my main goals and improved how I document my work."),
            ("assistant", "What's one area you'd like to grow in next cycle?"),
            ("user", "I'd like to take on more mentoring and get better at prioritizing competing deadlines."),
        ]
    if relationship == "manager":
        return [
            ("assistant", f"How would you describe {first}'s reliability and quality of work this cycle?"),
            ("user", f"{first} is dependable and consistently delivers accurate work with little oversight."),
            ("assistant", "Any development areas you'd highlight?"),
            ("user", "Could delegate a bit more and speak up earlier when timelines slip."),
        ]
    if relationship == "report":
        return [
            ("assistant", f"How well does {first} support you and remove blockers?"),
            ("user", f"{first} is approachable and makes time to unblock the team quickly."),
            ("assistant", "What could they do better as a manager?"),
            ("user", "More regular one-on-ones would help; sometimes feedback comes in bursts."),
        ]
    return [  # peer
        ("assistant", f"How is {first} to collaborate with across the team?"),
        ("user", f"{first} communicates early, shares context, and follows through on commitments."),
        ("assistant", "Anything that would make working together even better?"),
        ("user", "Occasionally responses lag during busy weeks, but nothing major."),
    ]


def wipe(conn):
    cycle = fetchone(conn, "SELECT id FROM cycles WHERE name = ?", (CYCLE_NAME,))
    if cycle:
        cid = cycle["id"]
        conn.execute(
            "DELETE FROM responses WHERE assignment_id IN "
            "(SELECT id FROM assignments WHERE cycle_id = ?)", (cid,))
        conn.execute(
            "DELETE FROM conversation_turns WHERE assignment_id IN "
            "(SELECT id FROM assignments WHERE cycle_id = ?)", (cid,))
        conn.execute("DELETE FROM assignments WHERE cycle_id = ?", (cid,))
        conn.execute("DELETE FROM cycle_participants WHERE cycle_id = ?", (cid,))
        conn.execute("DELETE FROM cycles WHERE id = ?", (cid,))
        print(f"Deleted demo cycle #{cid} and its assignments/responses/turns.")
    n = conn.execute(
        "DELETE FROM users WHERE email LIKE ?", (f"%@{DEMO_DOMAIN}",)).rowcount
    print(f"Deleted {n} demo user(s) (@{DEMO_DOMAIN}).")


def seed(conn):
    # Ensure the question bank exists (idempotent; prod already has it).
    admin = fetchone(conn, "SELECT id FROM users WHERE lower(email) = ?", (ADMIN_EMAIL,))
    if not admin:
        print(f"WARNING: admin {ADMIN_EMAIL} not found; created_by will be NULL.")
    created_by = admin["id"] if admin else None

    if fetchone(conn, "SELECT 1 FROM cycles WHERE name = ?", (CYCLE_NAME,)):
        print(f"Demo cycle '{CYCLE_NAME}' already exists. "
              f"Run `python seed_demo.py --wipe` first to re-seed. Nothing done.")
        return

    # --- Users (create manager first so manager_id resolves) ---
    ids = {}  # email-local -> user id
    for name, local, role, dept, _mgr in PEOPLE:
        existing = fetchone(conn, "SELECT id FROM users WHERE lower(email) = ?", (email_for(local),))
        if existing:
            ids[local] = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO users (name,email,password_hash,role,department) VALUES (?,?,?,?,?)",
                (name, email_for(local), hash_password(DEMO_PASSWORD), role, dept))
            ids[local] = cur.lastrowid
    for name, local, role, dept, mgr in PEOPLE:
        if mgr:
            conn.execute("UPDATE users SET manager_id = ? WHERE id = ?", (ids[mgr], ids[local]))
    print(f"Ensured {len(PEOPLE)} demo users (password '{DEMO_PASSWORD}').")

    id_to_local = {v: k for k, v in ids.items()}
    manager_of = {}
    for name, local, role, dept, mgr in PEOPLE:
        manager_of[ids[local]] = ids[mgr] if mgr else None

    # --- Cycle (active) + participants ---
    cur = conn.execute(
        "INSERT INTO cycles (name,description,status,start_date,end_date,created_by) "
        "VALUES (?,?,?,?,?,?)",
        (CYCLE_NAME, "Sample cycle with demo data for demonstration.",
         "active", "2026-07-01", "2026-09-30", created_by))
    cycle_id = cur.lastrowid
    participant_ids = list(ids.values())
    for uid in participant_ids:
        conn.execute("INSERT OR IGNORE INTO cycle_participants (cycle_id,user_id) VALUES (?,?)",
                     (cycle_id, uid))

    # --- Assignments (N x N, same algorithm as cycle_activate) ---
    demo_login_id = ids[DEMO_LOGIN]
    likert_qs = fetchall(
        conn, "SELECT id, department FROM questions WHERE is_active = 1 AND question_type = 'likert'")

    n_completed = n_pending = 0
    for ev in participant_ids:
        for su in participant_ids:
            rel = rel_of(ev, su, manager_of)
            cur = conn.execute(
                "INSERT OR IGNORE INTO assignments "
                "(cycle_id, evaluator_id, subject_id, relationship, status) VALUES (?,?,?,?,?)",
                (cycle_id, ev, su, rel, "pending"))
            aid = cur.lastrowid

            # Leave the demo-login user's OUTGOING evals pending for a live demo.
            if ev == demo_login_id:
                n_pending += 1
                continue

            # Everything else: mark completed with ratings + a short transcript.
            subj_local = id_to_local[su]
            subj_dept = next(d for _n, l, _r, d, _m in PEOPLE if l == subj_local)
            for q in likert_qs:
                # General questions apply to all; dept-specific only to matching dept.
                if q["department"] and q["department"] != subj_dept:
                    continue
                conn.execute(
                    "INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                    (aid, q["id"], rating_for(id_to_local[ev], subj_local, q["id"])))
            subj_name = next(n for n, l, _r, _d, _m in PEOPLE if l == subj_local)
            for role, content in transcript_for(subj_name, rel):
                conn.execute(
                    "INSERT INTO conversation_turns (assignment_id, role, content) VALUES (?,?,?)",
                    (aid, role, content))
            conn.execute(
                "UPDATE assignments SET status='completed', "
                "started_at=datetime('now','-5 days'), completed_at=datetime('now','-3 days') "
                "WHERE id = ?", (aid,))
            n_completed += 1

    print(f"Created cycle #{cycle_id} '{CYCLE_NAME}' (active) with "
          f"{n_completed} completed + {n_pending} pending assignments.")
    print(f"Live-demo login: {email_for(DEMO_LOGIN)} / {DEMO_PASSWORD} "
          f"({n_pending} pending evaluations to run).")
    print("Populated reports: log in as admin and open any subject's report "
          f"in cycle #{cycle_id} (e.g. Aisha Patel).")


def main():
    wipe_mode = "--wipe" in sys.argv[1:]
    seed_questions()  # ensure question bank exists (idempotent)
    with get_db() as conn:
        if wipe_mode:
            wipe(conn)
        else:
            seed(conn)


if __name__ == "__main__":
    main()
