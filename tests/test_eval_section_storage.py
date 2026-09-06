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


def test_section_for_asking_qid_returns_category_for_active_question(db):
    with get_db() as conn:
        q = fetchone(conn,
            "SELECT id, category FROM questions WHERE question_type = 'likert' AND is_active = 1 "
            "ORDER BY order_index LIMIT 1")
        assert eval_routes._section_for_asking_qid(conn, q["id"]) == q["category"]


def test_section_for_asking_qid_returns_none_for_unknown_id(db):
    with get_db() as conn:
        assert eval_routes._section_for_asking_qid(conn, 999999) is None


def test_section_for_asking_qid_returns_none_for_inactive_question(db):
    with get_db() as conn:
        q = fetchone(conn,
            "SELECT id FROM questions WHERE question_type = 'likert' ORDER BY order_index LIMIT 1")
        conn.execute("UPDATE questions SET is_active = 0 WHERE id = ?", (q["id"],))
        conn.commit()
        assert eval_routes._section_for_asking_qid(conn, q["id"]) is None


def test_section_for_asking_qid_returns_none_for_none_id(db):
    with get_db() as conn:
        assert eval_routes._section_for_asking_qid(conn, None) is None


def test_message_route_overrides_model_claimed_section_with_question_category_REGRESSION(
    client_with_assignment, monkeypatch):
    """Regression test for the reported defect: the turn that OPENS a section by
    posing that section's first question was stored with the previous section's
    label because the route trusted the model's `section` claim verbatim. The
    route must derive the stored section from the DB's question category
    whenever `asking_question_id` names a real, active question — overriding
    whatever the model said in `section` — exactly as `_rating_ids_for` already
    overrides button visibility rather than trusting a model-reported marker.
    """
    client, ids = client_with_assignment
    with get_db() as conn:
        qid = fetchone(conn,
            "SELECT id FROM questions WHERE category = 'Communication Skills' AND question_type = 'likert' "
            "ORDER BY order_index LIMIT 1")["id"]

    # Model poses question `qid` (category "Communication Skills") but mislabels
    # the turn's section as "Introduction" -- the exact boundary bug reported.
    monkeypatch.setattr(eval_routes, "call_claude",
        lambda system_prompt, messages, sections:
            ("Let's start with the technical side of things.", False, qid, "Introduction"))
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


def test_message_route_falls_back_to_model_section_when_no_question_is_asked(
    client_with_assignment, monkeypatch):
    """When `asking_question_id` is null (intro, probe, or wrap-up turn), there is
    no question category to derive a section from, so the route must keep using
    whatever `section` the model reported."""
    client, ids = client_with_assignment

    monkeypatch.setattr(eval_routes, "call_claude",
        lambda system_prompt, messages, sections:
            ("That's a 2 -- can you tell me a bit more about what's been challenging?",
             False, None, "Communication Skills"))
    login(client, "eve@test.local")

    r = client.post(f"/eval/{ids['assignment_id']}/message", json={"message": "RATING:1:2"})

    assert r.status_code == 200
    assert r.json()["rating_ids"] == []
    with get_db() as conn:
        row = fetchone(conn,
            "SELECT rating_question_id, section FROM conversation_turns "
            "WHERE assignment_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            (ids["assignment_id"],))
    assert row == {"rating_question_id": None, "section": "Communication Skills"}
