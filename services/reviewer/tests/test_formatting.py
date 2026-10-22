from formatting import build_inline_comments, build_summary

FINDINGS = [
    {"file": "app/db.py", "line": 11, "severity": "error", "message": "SQL injection", "agent": "security", "inline": True},
    {"file": "app/db.py", "line": "12", "severity": "warning", "message": "No error handling", "agent": "architecture", "inline": True},
    {"file": "app/db.py", "line": 99, "severity": "info", "message": "Rename x", "agent": "style", "inline": False},
    {"file": "app/db.py", "line": None, "severity": "warning", "message": "File too long", "agent": "static_analysis"},
]


def test_inline_comments_only_for_lines_in_diff():
    comments = build_inline_comments(FINDINGS)
    assert [(c["path"], c["line"]) for c in comments] == [("app/db.py", 11), ("app/db.py", 12)]
    assert comments[0]["side"] == "RIGHT"
    assert "ERROR" in comments[0]["body"] and "SQL injection" in comments[0]["body"]


def test_summary_counts_and_lists_only_non_inline_findings():
    summary = build_summary(FINDINGS)
    assert "**4 findings**" in summary
    assert "🔴 1 error · 🟡 2 warnings · 🔵 1 info" in summary
    assert "| security | 1 | 0 | 0 |" in summary
    assert "Findings outside the changed lines (2)" in summary
    assert "Rename x" in summary and "File too long" in summary
    assert "SQL injection" not in summary


def test_summary_include_all_lists_everything():
    summary = build_summary(FINDINGS, include_all=True)
    assert "All findings (4)" in summary
    assert "SQL injection" in summary


def test_summary_when_clean():
    assert "No issues found" in build_summary([])
