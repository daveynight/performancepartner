"""The silent rating-revision endpoint: POST /eval/{id}/rating.

Changing a score the evaluator already gave must update `responses` without
calling the interviewer and without adding a turn to the transcript. That
absence of a turn is the whole point of the endpoint -- the conversational
path already exists on /eval/{id}/message.
"""
from database import get_db, fetchone, fetchall
from tests.conftest import login


def _likert_qid(category="Communication Skills"):
    with get_db() as conn:
        return fetchone(conn,
            "SELECT id FROM questions WHERE category = ? AND question_type = 'likert' "
            "AND is_active = 1 ORDER BY order_index LIMIT 1", (category,))["id"]


def _rating(assignment_id, question_id):
    with get_db() as conn:
        row = fetchone(conn,
            "SELECT rating FROM responses WHERE assignment_id = ? AND question_id = ?",
            (assignment_id, question_id))
    return row["rating"] if row else None


def _turn_count(assignment_id):
    with get_db() as conn:
        return fetchone(conn,
            "SELECT COUNT(*) AS n FROM conversation_turns WHERE assignment_id = ?",
            (assignment_id,))["n"]


def test_revising_a_score_updates_it_without_adding_a_conversation_turn(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    with get_db() as conn:
        conn.execute("INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                     (aid, qid, 5))
    before = _turn_count(aid)
    login(client, "eve@test.local")

    r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": 2})

    assert r.status_code == 200
    assert r.json() == {"question_id": qid, "value": 2}
    assert _rating(aid, qid) == 2
    assert _turn_count(aid) == before, "revision must not write a conversation turn"


def test_revising_a_never_scored_question_records_the_score(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid("Cooperation & Teamwork")
    assert _rating(aid, qid) is None
    login(client, "eve@test.local")

    r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": 4})

    assert r.status_code == 200
    assert _rating(aid, qid) == 4


def test_revising_does_not_duplicate_the_responses_row(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    login(client, "eve@test.local")

    for value in (1, 3, 5):
        assert client.post(f"/eval/{aid}/rating",
                           json={"question_id": qid, "value": value}).status_code == 200

    with get_db() as conn:
        rows = fetchall(conn,
            "SELECT rating FROM responses WHERE assignment_id = ? AND question_id = ?",
            (aid, qid))
    assert rows == [{"rating": 5}], "repeated revisions must upsert, not accumulate rows"


def test_out_of_range_value_is_rejected_and_leaves_the_score_alone(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    with get_db() as conn:
        conn.execute("INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                     (aid, qid, 3))
    login(client, "eve@test.local")

    for bad in (0, 6, -1, 99):
        r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": bad})
        assert r.status_code == 400, f"value {bad} should be rejected"
    assert _rating(aid, qid) == 3


def test_non_integer_value_is_rejected(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    login(client, "eve@test.local")

    for bad in ("three", None, 2.5, [3]):
        r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": bad})
        assert r.status_code == 400, f"value {bad!r} should be rejected"
    assert _rating(aid, qid) is None


def test_a_text_question_cannot_be_scored(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    with get_db() as conn:
        qid = fetchone(conn,
            "SELECT id FROM questions WHERE question_type = 'text' AND is_active = 1 LIMIT 1")["id"]
    login(client, "eve@test.local")

    r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": 4})

    assert r.status_code == 400
    assert _rating(aid, qid) is None


def test_unknown_question_is_rejected(client_with_assignment):
    client, ids = client_with_assignment
    login(client, "eve@test.local")

    r = client.post(f"/eval/{ids['assignment_id']}/rating",
                    json={"question_id": 999999, "value": 4})

    assert r.status_code == 400


def test_a_completed_interview_cannot_be_revised(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    with get_db() as conn:
        conn.execute("INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                     (aid, qid, 3))
        conn.execute("UPDATE assignments SET status = 'completed' WHERE id = ?", (aid,))
    login(client, "eve@test.local")

    r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": 1})

    assert r.status_code == 400
    assert _rating(aid, qid) == 3, "a finished interview's scores are settled"


def test_another_staff_member_cannot_revise_someone_elses_scores(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    with get_db() as conn:
        conn.execute("INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                     (aid, qid, 3))
    login(client, "sam@test.local")  # the subject, not the evaluator

    r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": 1})

    assert r.status_code == 403
    assert _rating(aid, qid) == 3


# --- The chat page must surface earlier scores so they can be revised -------


def _seed_scored_exchange(aid, qid):
    """An assistant turn that posed `qid`, answered, then the interview moved on."""
    with get_db() as conn:
        conn.execute("INSERT INTO conversation_turns (assignment_id, role, content, "
                     "rating_question_id, section) VALUES (?,?,?,?,?)",
                     (aid, "assistant", "How clearly does Sam communicate?", qid,
                      "Communication Skills"))
        conn.execute("INSERT INTO conversation_turns (assignment_id, role, content) "
                     "VALUES (?,?,?)", (aid, "user", f"RATING:{qid}:5"))
        conn.execute("INSERT INTO conversation_turns (assignment_id, role, content, section) "
                     "VALUES (?,?,?,?)",
                     (aid, "assistant", "Let's move on to teamwork.", "Cooperation & Teamwork"))
        conn.execute("INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                     (aid, qid, 5))


def test_reloaded_page_offers_buttons_for_an_already_scored_question(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    _seed_scored_exchange(aid, qid)
    login(client, "eve@test.local")

    html = client.get(f"/eval/{aid}").text

    assert f'id="ratings-{qid}"' in html, "the earlier question needs a rating row on reload"
    assert f'submitRating({qid}, 3)' in html, "each 1-5 button must be clickable"
    # The RATING: user turn must not surface as a chat bubble. Match the real
    # message, since the bare token also lives in the page's JavaScript.
    assert f"RATING:{qid}:5" not in html, "raw rating messages stay out of the transcript"


def test_reloaded_page_marks_the_score_that_was_given(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    _seed_scored_exchange(aid, qid)
    login(client, "eve@test.local")

    html = client.get(f"/eval/{aid}").text
    row = html.split(f'id="ratings-{qid}"', 1)[1].split("</div>", 3)[0]

    assert "bg-indigo-600" in row, "the chosen score should be visibly selected"


def test_a_text_question_gets_no_rating_row(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    with get_db() as conn:
        qid = fetchone(conn,
            "SELECT id FROM questions WHERE question_type = 'text' AND is_active = 1 LIMIT 1")["id"]
        conn.execute("INSERT INTO conversation_turns (assignment_id, role, content, "
                     "rating_question_id) VALUES (?,?,?,?)",
                     (aid, "assistant", "Any additional comments?", qid))
    login(client, "eve@test.local")

    html = client.get(f"/eval/{aid}").text

    assert f'id="ratings-{qid}"' not in html


def test_revisable_excludes_deactivated_and_non_likert_questions(client_with_assignment):
    """An admin can deactivate a question mid-cycle, or change its type. A score
    already recorded against it must stop being offered for revision."""
    import routes.eval as eval_routes

    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    likert = _likert_qid()
    with get_db() as conn:
        text_q = fetchone(conn,
            "SELECT id FROM questions WHERE question_type = 'text' AND is_active = 1 LIMIT 1")["id"]
        retired = fetchone(conn,
            "SELECT id FROM questions WHERE question_type = 'likert' AND id != ? "
            "AND is_active = 1 LIMIT 1", (likert,))["id"]
        for q in (likert, text_q, retired):
            conn.execute("INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                         (aid, q, 4))
        conn.execute("UPDATE questions SET is_active = 0 WHERE id = ?", (retired,))

    with get_db() as conn:
        revisable = eval_routes._revisable_ratings(conn, aid)

    assert likert in revisable
    assert text_q not in revisable, "a text question is not scorable"
    assert retired not in revisable, "a deactivated question is no longer revisable"


def test_a_deactivated_question_cannot_be_revised_via_the_endpoint(client_with_assignment):
    client, ids = client_with_assignment
    aid = ids["assignment_id"]
    qid = _likert_qid()
    with get_db() as conn:
        conn.execute("INSERT INTO responses (assignment_id, question_id, rating) VALUES (?,?,?)",
                     (aid, qid, 4))
        conn.execute("UPDATE questions SET is_active = 0 WHERE id = ?", (qid,))
    login(client, "eve@test.local")

    r = client.post(f"/eval/{aid}/rating", json={"question_id": qid, "value": 1})

    assert r.status_code == 400
    assert _rating(aid, qid) == 4
