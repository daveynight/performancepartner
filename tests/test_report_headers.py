import html as html_lib
import re

from database import get_db
from tests.conftest import login


def _complete_with_turns(ids, turns):
    """Mark the fixture assignment completed and insert (role, content, section) turns."""
    with get_db() as conn:
        for role, content, section in turns:
            conn.execute(
                "INSERT INTO conversation_turns (assignment_id, role, content, section) VALUES (?,?,?,?)",
                (ids["assignment_id"], role, content, section))
        conn.execute("UPDATE assignments SET status = 'completed' WHERE id = ?", (ids["assignment_id"],))


def _report_html(client, ids):
    login(client, "admin@test.local")
    r = client.get(f"/reports/{ids['cycle_id']}/user/{ids['subject_id']}")
    assert r.status_code == 200
    return r.text


def test_report_shows_section_headers_in_order(client_with_assignment):
    client, ids = client_with_assignment
    _complete_with_turns(ids, [
        ("user", "__START__", None),
        ("assistant", "Hi Eve, thanks for making time.", "Introduction"),
        ("user", "Happy to help.", None),
        ("assistant", "Let's start with Communication Skills.", "Communication Skills"),
        ("user", "RATING:12:4", None),
        ("assistant", "What did Sam do particularly well here?", "Communication Skills"),
        ("user", "Sam rewrote the onboarding packet.", None),
        ("assistant", "That's everything — thank you.", "Closing"),
    ])
    html = _report_html(client, ids)

    headers = re.findall(r'data-section-header>\s*([^<]+?)\s*<', html)
    assert headers == ["Introduction", "Communication Skills", "Closing"]
    # The header sits after the intro turn and before the first turn of its section.
    comm_header = re.search(r'data-section-header>\s*Communication Skills', html).start()
    assert html.index("Hi Eve, thanks for making time.") < comm_header < html.index("particularly well here?")
    # Filtered turns stay filtered.
    assert "RATING:12:4" not in html
    assert "__START__" not in html


def test_report_shows_ampersand_section_header_correctly(client_with_assignment):
    """Several real category names contain an ampersand (e.g. "Cooperation &
    Teamwork", "Productivity & Technical Knowledge"). Jinja2 autoescapes, so
    the raw HTML the template emits holds the escaped `&amp;` form -- that is
    correct behavior and the template does not (and should not) use `|safe`.
    Confirm both ends of that: the raw HTML contains the escaped form, and
    unescaping it recovers exactly the real category name a reader sees.
    """
    client, ids = client_with_assignment
    _complete_with_turns(ids, [
        ("assistant", "Let's talk about how you work with others.", "Cooperation & Teamwork"),
        ("user", "Sure, happy to.", None),
        ("assistant", "Thanks, that's everything.", "Closing"),
    ])
    html = _report_html(client, ids)

    # The raw response body carries the escaped form, not the literal "&".
    assert "Cooperation &amp; Teamwork" in html
    assert "Cooperation & Teamwork" not in html

    # Unescaping what the reader's browser would render recovers the exact
    # category name -- proving the header reads correctly, not just that
    # escaping happened.
    headers = [html_lib.unescape(h) for h in re.findall(r'data-section-header>\s*([^<]+?)\s*<', html)]
    assert headers == ["Cooperation & Teamwork", "Closing"]


def test_report_without_sections_renders_no_headers(client_with_assignment):
    client, ids = client_with_assignment
    _complete_with_turns(ids, [
        ("assistant", "Hi Eve.", None),
        ("user", "Hello.", None),
        ("assistant", "Thanks, bye.", None),
    ])
    html = _report_html(client, ids)
    assert "data-section-header" not in html
    assert "Hi Eve." in html and "Thanks, bye." in html
