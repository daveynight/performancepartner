import seed_demo


def _sections(turns):
    return [s for _role, _content, s in turns]


def test_transcript_turns_are_role_content_section_triples():
    turns = seed_demo.transcript_for("aisha", "maria", "Maria Santos", "report", "HMIS")
    assert all(len(t) == 3 for t in turns)
    assert turns[0] == ("user", "__START__", "Introduction")
    assert turns[-1][0] == "assistant"
    assert turns[-1][2] == "Closing"


def test_every_area_the_relationship_unlocks_gets_its_category_label():
    turns = seed_demo.transcript_for("aisha", "maria", "Maria Santos", "manager", "HMIS")
    labels = _sections(turns)
    for _key, category, _scope in seed_demo.AREAS:
        assert category in labels, category
    assert "HMIS" in labels          # dept-specific block uses the real category name
    assert "Comments" in labels
    assert "Goals" in labels         # manager scope asks the goal questions


def test_peer_scoping_turns_are_in_introduction():
    subject_name = "Tom Reyes"
    first = subject_name.split()[0]
    turns = seed_demo.transcript_for("aisha", "tom", subject_name, "peer", "Finance")

    # The fixed assistant scoping strings transcript_for() emits for a peer
    # (see seed_demo.py's `say()` calls under "Scoping (peers only, matching
    # the real prompt)"). Matched on exact text rather than a loose substring
    # like "scoping"/"peers", which also matches unrelated content elsewhere
    # in seed_demo.py (e.g. "Rescoping" in a self-evaluation answer).
    scoping_texts = {
        f"First, a couple of quick scoping questions. Are you on {first}'s team — do you work with them directly day to day?",
        f"Thanks. And are you {first}'s manager?",
        "Perfect — that means I'll cover the general and team-specific questions with you.",
    }
    scoping = [t for t in turns if t[1] in scoping_texts]
    assert len(scoping) == len(scoping_texts), "expected all three peer scoping turns"
    assert all(s == "Introduction" for _r, _c, s in scoping)
    assert "Goals" not in _sections(turns)  # peers never reach manager-scope questions
    assert "Finance" in _sections(turns)     # Tom's department block


def test_section_labels_change_only_on_assistant_turns():
    turns = seed_demo.transcript_for("aisha", "maria", "Maria Santos", "manager", "HMIS")
    for prev, cur in zip(turns, turns[1:]):
        if cur[2] != prev[2]:
            assert cur[0] == "assistant", f"section changed on a user turn: {cur}"
