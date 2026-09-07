import interview


def _q(qid, category, order_index):
    return {"id": qid, "category": category, "order_index": order_index,
            "question_type": "likert", "text": f"Q{qid}", "scope": "general"}


def test_section_labels_are_intro_then_categories_in_order_then_closing():
    questions = [
        _q(3, "Communication Skills", 201),
        _q(1, "Productivity & Technical Knowledge", 101),
        _q(2, "Productivity & Technical Knowledge", 102),
        _q(4, "Goals", 801),
    ]
    assert interview.section_labels_for(questions) == [
        "Introduction",
        "Productivity & Technical Knowledge",
        "Communication Skills",
        "Goals",
        "Closing",
    ]


def test_section_labels_with_no_questions_still_has_intro_and_closing():
    assert interview.section_labels_for([]) == ["Introduction", "Closing"]


def test_reserved_labels_are_never_duplicated():
    questions = [
        _q(1, "Introduction", 101),
        _q(2, "Communication Skills", 201),
        _q(3, "Closing", 301),
    ]
    labels = interview.section_labels_for(questions)
    assert labels == ["Introduction", "Communication Skills", "Closing"]
    assert len(labels) == len(set(labels))


def test_tool_has_section_enum_between_last_answer_and_message():
    tool = interview.build_interview_tool(["Introduction", "Communication Skills", "Closing"])
    props = tool["input_schema"]["properties"]
    assert list(props) == ["last_answer", "section", "message", "asking_question_id", "interview_complete"]
    assert props["section"]["type"] == "string"
    assert props["section"]["enum"] == ["Introduction", "Communication Skills", "Closing"]
    assert tool["input_schema"]["required"] == [
        "last_answer", "section", "message", "asking_question_id", "interview_complete"]
    assert tool["strict"] is True
    assert tool["input_schema"]["additionalProperties"] is False


def test_tool_keeps_existing_fields_unchanged():
    tool = interview.build_interview_tool(["Introduction", "Closing"])
    props = tool["input_schema"]["properties"]
    assert props["last_answer"]["enum"] == ["specific", "vague", "declined", "not_applicable"]
    assert props["asking_question_id"]["type"] == ["integer", "null"]
    assert props["interview_complete"]["type"] == "boolean"
    assert tool["name"] == "interview_turn"


class _FakeBlock:
    type = "tool_use"

    def __init__(self, tool_input):
        self.input = tool_input


class _FakeMessages:
    def __init__(self, tool_input):
        self._input = tool_input
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Resp", (), {"content": [_FakeBlock(self._input)]})()


class _FakeClient:
    def __init__(self, tool_input):
        self.messages = _FakeMessages(tool_input)


def test_call_claude_returns_section_and_sends_dynamic_enum(monkeypatch):
    fake = _FakeClient({
        "last_answer": "not_applicable",
        "section": "Communication Skills",
        "message": "  Let's talk about communication.  ",
        "asking_question_id": 7,
        "interview_complete": False,
    })
    monkeypatch.setattr(interview, "client", fake)
    sections = ["Introduction", "Communication Skills", "Closing"]

    result = interview.call_claude("sys", [{"role": "user", "content": "__START__"}], sections)

    assert result == ("Let's talk about communication.", False, 7, "Communication Skills")
    sent = fake.messages.calls[0]
    assert sent["tool_choice"] == {"type": "tool", "name": "interview_turn"}
    assert sent["tools"][0]["input_schema"]["properties"]["section"]["enum"] == sections


def test_call_claude_tolerates_missing_section(monkeypatch):
    fake = _FakeClient({"last_answer": "specific", "message": "Thanks!",
                        "asking_question_id": None, "interview_complete": True})
    monkeypatch.setattr(interview, "client", fake)
    assert interview.call_claude("sys", [], ["Introduction", "Closing"]) == ("Thanks!", True, None, None)


def test_prompt_explains_the_section_field():
    assignment = {"relationship": "manager"}
    evaluee = {"name": "Sam Subject", "department": None}
    evaluator = {"name": "Eve Evaluator"}
    prompt = interview.build_system_prompt(assignment, evaluee, evaluator, [])
    assert "`section`" in prompt
    assert "`Introduction`" in prompt
    assert "`Closing`" in prompt
