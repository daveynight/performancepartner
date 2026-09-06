import routes.eval as eval_routes
from database import create_tables, get_db, fetchone, fetchall
from tests.conftest import login


def test_conversation_turns_gains_section_column_and_migration_is_idempotent(db):
    create_tables()  # second run on an already-migrated DB must not raise
    with get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(conversation_turns)")}
    assert "section" in cols
    assert "rating_question_id" in cols  # existing migration still present


def test_message_route_stores_the_declared_section(client_with_assignment, monkeypatch):
    client, ids = client_with_assignment
    seen = {}

    def fake_call_claude(system_prompt, messages, sections):
        seen["sections"] = sections
        return "Hi Eve, thanks for making time.", False, None, "Introduction"

    monkeypatch.setattr(eval_routes, "call_claude", fake_call_claude)
    login(client, "eve@test.local")

    r = client.post(f"/eval/{ids['assignment_id']}/message", json={"message": "__START__"})

    assert r.status_code == 200
    assert r.json() == {"reply": "Hi Eve, thanks for making time.", "rating_ids": [], "completed": False}
    assert seen["sections"][0] == "Introduction"
    assert seen["sections"][-1] == "Closing"
    assert "Communication Skills" in seen["sections"]

    with get_db() as conn:
        turns = fetchall(conn,
            "SELECT role, content, section FROM conversation_turns WHERE assignment_id = ? ORDER BY id",
            (ids["assignment_id"],))
    assert turns == [
        {"role": "user", "content": "__START__", "section": None},
        {"role": "assistant", "content": "Hi Eve, thanks for making time.", "section": "Introduction"},
    ]


def test_message_route_stores_category_section_alongside_rating_id(client_with_assignment, monkeypatch):
    client, ids = client_with_assignment
    with get_db() as conn:
        qid = fetchone(conn,
            "SELECT id FROM questions WHERE category = 'Communication Skills' AND question_type = 'likert' "
            "ORDER BY order_index LIMIT 1")["id"]

    monkeypatch.setattr(eval_routes, "call_claude",
        lambda system_prompt, messages, sections:
            ("How clearly does Sam communicate?", False, qid, "Communication Skills"))
    login(client, "eve@test.local")

    r = client.post(f"/eval/{ids['assignment_id']}/message", json={"message": "Yes, same team."})

    assert r.status_code == 200
    assert r.json()["rating_ids"] == [qid]
    with get_db() as conn:
        row = fetchone(conn,
            "SELECT rating_question_id, section FROM conversation_turns "
            "WHERE assignment_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            (ids["assignment_id"],))
    assert row == {"rating_question_id": qid, "section": "Communication Skills"}
