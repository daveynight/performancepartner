import os
import sqlite3
from contextlib import contextmanager

DATABASE_PATH = os.getenv("DATABASE_PATH", "performancepartner.db")


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetchone(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def fetchall(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def create_tables():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            email        TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'staff',
            department   TEXT,
            manager_id   INTEGER REFERENCES users(id),
            is_active    INTEGER NOT NULL DEFAULT 1,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS questions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category      TEXT NOT NULL,
            text          TEXT NOT NULL,
            question_type TEXT NOT NULL DEFAULT 'likert',
            scope         TEXT NOT NULL DEFAULT 'general',
            department    TEXT,
            order_index   INTEGER NOT NULL DEFAULT 0,
            is_active     INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS cycles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            status      TEXT NOT NULL DEFAULT 'draft',
            start_date  DATE,
            end_date    DATE,
            created_by  INTEGER REFERENCES users(id),
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cycle_questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id    INTEGER NOT NULL REFERENCES cycles(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            order_index INTEGER NOT NULL DEFAULT 0,
            UNIQUE(cycle_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS cycle_participants (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER NOT NULL REFERENCES cycles(id) ON DELETE CASCADE,
            user_id  INTEGER NOT NULL REFERENCES users(id),
            UNIQUE(cycle_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id             INTEGER NOT NULL REFERENCES cycles(id),
            evaluator_id         INTEGER NOT NULL REFERENCES users(id),
            subject_id           INTEGER NOT NULL REFERENCES users(id),
            relationship         TEXT NOT NULL,
            on_team              INTEGER,
            is_manager_confirmed INTEGER,
            status               TEXT NOT NULL DEFAULT 'pending',
            started_at           TIMESTAMP,
            completed_at         TIMESTAMP,
            UNIQUE(cycle_id, evaluator_id, subject_id)
        );

        CREATE TABLE IF NOT EXISTS conversation_turns (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            role          TEXT NOT NULL,
            content       TEXT NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS responses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            question_id   INTEGER NOT NULL REFERENCES questions(id),
            rating        INTEGER,
            text_response TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Lightweight, idempotent migration (no framework in this app):
        # records which likert question an assistant turn posed, so rating
        # buttons can be re-rendered after a page reload.
        try:
            conn.execute("ALTER TABLE conversation_turns ADD COLUMN rating_question_id INTEGER")
        except Exception:
            pass  # column already exists


def seed_admin():
    from auth import hash_password as hp
    with get_db() as conn:
        if fetchone(conn, "SELECT 1 FROM users LIMIT 1"):
            return
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
            ("Admin", "hmis@partnersincareoahu.org", hp("changeme"), "admin"),
        )
        print("=" * 60)
        print("Default admin created:")
        print("  Email:    admin@partnersincareoahu.org")
        print("  Password: changeme")
        print("  Change this password immediately in Admin > Users.")
        print("=" * 60)
