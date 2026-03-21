from browser_agent.dom_snapshot import format_snapshot_for_llm


def test_format_snapshot_truncates() -> None:
    snap = {"visible_text": "x" * 50_000, "interactive": [{"text": "a"}] * 200}
    s = format_snapshot_for_llm(snap, max_chars=1000)
    assert isinstance(s, str)
    assert len(s) <= 1000

