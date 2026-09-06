"""Test fixtures.

Environment is configured at import time, before any project module loads:
`database.py` reads DATABASE_PATH when imported, and `interview.py` builds an
Anthropic client from ANTHROPIC_API_KEY when imported. `main.py` calls
load_dotenv(), which does not override variables that are already set.
"""
import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="pp-tests-")
os.environ["DATABASE_PATH"] = os.path.join(_TMP_DIR, "test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-never-used")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def db():
    """A fresh schema plus the seeded question bank, for one test."""
    from database import create_tables
    from seed import seed_questions

    path = os.environ["DATABASE_PATH"]
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    create_tables()
    seed_questions()
    yield path


@pytest.fixture
def client_with_assignment(db):
    """A running app with an admin, an evaluator (Eve), a subject (Sam), an
    active cycle, and one pending peer assignment Eve -> Sam.

    Yields (client, ids). Nobody is logged in yet; call login(client, email).
    """
    import main
    from auth import hash_password
    from database import get_db, fetchone

    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
            ("Test Admin", "admin@test.local", hash_password("pw"), "admin"))
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, department) VALUES (?,?,?,?,?)",
            ("Eve Evaluator", "eve@test.local", hash_password("pw"), "staff", "HMIS"))
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, department) VALUES (?,?,?,?,?)",
            ("Sam Subject", "sam@test.local", hash_password("pw"), "staff", "HMIS"))
        eve = fetchone(conn, "SELECT id FROM users WHERE email = 'eve@test.local'")["id"]
        sam = fetchone(conn, "SELECT id FROM users WHERE email = 'sam@test.local'")["id"]
        cur = conn.execute("INSERT INTO cycles (name, status) VALUES ('Test Cycle', 'active')")
        cycle_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO assignments (cycle_id, evaluator_id, subject_id, relationship, status) "
            "VALUES (?,?,?,?,?)",
            (cycle_id, eve, sam, "peer", "pending"))
        assignment_id = cur.lastrowid

    ids = {"assignment_id": assignment_id, "cycle_id": cycle_id,
           "evaluator_id": eve, "subject_id": sam}
    with TestClient(main.app) as client:  # runs startup hooks (all idempotent)
        yield client, ids


def login(client: TestClient, email: str, password: str = "pw") -> None:
    r = client.post("/login", data={"email": email, "password": password},
                    follow_redirects=False)
    assert r.status_code == 303, f"login failed for {email}: {r.status_code}"
