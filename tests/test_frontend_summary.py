from pathlib import Path


HTML = (Path(__file__).parents[1] / "index.html").read_text(encoding="utf-8")


def test_decision_summary_reads_all_three_scoring_tools():
    start = HTML.index("function decisionSummary")
    end = HTML.index("function cafeCard", start)
    implementation = HTML[start:end]

    assert "score_fairest_option" in implementation
    assert "score_fastest_option" in implementation
    assert "score_best_cafe_option" in implementation
    assert "Tool-derived results" in implementation
    assert "Best cafe overall" in implementation
    assert "choosing it prioritizes cafe quality" in implementation
    assert "get_transit_matrix" in implementation
    assert "commuteImpact" in implementation
    assert "Recommended for your priority" in HTML


def test_decision_summary_precedes_results_and_tool_details():
    start = HTML.index("async function send")
    end = HTML.index("reset.addEventListener", start)
    send = HTML[start:end]

    assert send.index("decisionSummary(calls)") < send.index("resultCards(calls)")
    assert send.index("resultCards(calls)") < send.index("toolLog(calls)")


def test_priority_instruction_is_not_echoed_as_user_authored_text():
    start = HTML.index("async function send")
    end = HTML.index("reset.addEventListener", start)
    send = HTML[start:end]

    assert "body:JSON.stringify({message,session_id:sessionId})" in send
    assert "addMessage('you',text)" in send
    assert "addMessage('you',message)" not in send


def test_mobile_composer_and_explanation_stay_readable():
    assert 'placeholder="Where is everyone coming from?"' in HTML
    assert "input.style.overflowY=input.scrollHeight>limit?'auto':'hidden'" in HTML
    assert "detail.open=true" in HTML
    assert "Why this recommendation" in HTML


def test_readme_queries_use_an_explicit_meeting_date_and_timezone():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "October 10, 2026 at 2:00 PM Eastern Time" in readme
    assert "coffee Saturday at 2pm" not in readme
