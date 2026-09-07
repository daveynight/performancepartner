from routes.reports import group_turns_by_section


def _t(role, content, section=None):
    return {"role": role, "content": content, "section": section}


def test_assistant_turn_with_new_section_opens_a_group_and_user_turns_follow_it():
    turns = [
        _t("assistant", "Hi, welcome.", "Introduction"),
        _t("user", "Hello"),
        _t("assistant", "Let's talk about communication.", "Communication Skills"),
        _t("user", "Sure"),
        _t("assistant", "Anything concrete?", "Communication Skills"),
        _t("user", "She rewrote the packet."),
        _t("assistant", "Thanks, that's everything.", "Closing"),
    ]
    groups = group_turns_by_section(turns)
    assert [g["label"] for g in groups] == ["Introduction", "Communication Skills", "Closing"]
    assert [t["content"] for t in groups[1]["turns"]] == [
        "Let's talk about communication.", "Sure", "Anything concrete?", "She rewrote the packet."]
    assert groups[2]["turns"] == [turns[-1]]


def test_legacy_turns_without_sections_form_one_unlabeled_group():
    turns = [_t("assistant", "Hi"), _t("user", "Hello"), _t("assistant", "Bye")]
    groups = group_turns_by_section(turns)
    assert groups == [{"label": None, "turns": turns}]


def test_assistant_turn_with_null_section_stays_in_current_group():
    turns = [
        _t("assistant", "Let's talk about teamwork.", "Cooperation & Teamwork"),
        _t("user", "Ok"),
        _t("assistant", "Could you say more?"),  # section None mid-section
        _t("user", "He covered my shift."),
    ]
    groups = group_turns_by_section(turns)
    assert len(groups) == 1
    assert groups[0]["label"] == "Cooperation & Teamwork"
    assert len(groups[0]["turns"]) == 4


def test_repeated_same_section_does_not_open_a_new_group():
    turns = [
        _t("assistant", "Q1", "Communication Skills"),
        _t("user", "A1"),
        _t("assistant", "Q2", "Communication Skills"),
    ]
    assert len(group_turns_by_section(turns)) == 1


def test_user_turn_before_any_assistant_turn_lands_in_unlabeled_group():
    turns = [_t("user", "hello?"), _t("assistant", "Hi!", "Introduction")]
    groups = group_turns_by_section(turns)
    assert [g["label"] for g in groups] == [None, "Introduction"]


def test_missing_section_key_is_treated_as_none():
    turns = [{"role": "assistant", "content": "Hi"}, {"role": "user", "content": "Hey"}]
    assert group_turns_by_section(turns) == [{"label": None, "turns": turns}]


def test_empty_input_gives_empty_output():
    assert group_turns_by_section([]) == []
