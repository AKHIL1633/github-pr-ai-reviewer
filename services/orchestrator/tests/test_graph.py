import asyncio
import json

import graph
from graph import build_graph, build_system_prompt, merge_node, parse_findings

DIFF = """diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -1,2 +1,3 @@
 import os
+API_KEY = "sk-live-123"
 x = 1
"""


def test_parse_findings_accepts_object_list_and_code_fence():
    item = {"file": "a.py", "line": 3, "severity": "warning", "message": "m"}
    assert parse_findings(json.dumps({"findings": [item]})) == [item]
    assert parse_findings(json.dumps([item])) == [item]
    assert parse_findings(f"```json\n{json.dumps([item])}\n```") == [item]


def test_parse_findings_normalizes_and_drops_bad_items():
    raw = json.dumps({"findings": [
        {"file": "a.py", "line": "12-14", "severity": "HIGH", "message": "m1"},
        {"file": "a.py", "line": None, "severity": "low", "message": "m2"},
        {"line": 3, "message": "no file"},
    ]})
    assert parse_findings(raw) == [
        {"file": "a.py", "line": 12, "severity": "error", "message": "m1"},
        {"file": "a.py", "line": None, "severity": "info", "message": "m2"},
    ]


def test_parse_findings_garbage_returns_empty():
    assert parse_findings("I could not review this") == []
    assert parse_findings("") == []


def test_system_prompt_includes_repo_patterns():
    prompt = build_system_prompt("security", ["Hardcoded AWS keys"])
    assert "Hardcoded AWS keys" in prompt
    assert '"findings"' in prompt


def test_merge_dedupes_sorts_flags_inline_and_drops_unknown_files():
    state = {
        "commentable": {"a.py": {1, 2, 3}},
        "findings": [
            {"file": "a.py", "line": 2, "severity": "info", "message": "Naming", "agent": "style"},
            {"file": "a.py", "line": 2, "severity": "info", "message": "naming ", "agent": "static_analysis"},
            {"file": "a.py", "line": 9, "severity": "error", "message": "Secret", "agent": "security"},
            {"file": "ghost.py", "line": 1, "severity": "error", "message": "x", "agent": "security"},
        ],
    }
    review = merge_node(state)["review"]
    assert [(f["file"], f["line"], f["severity"]) for f in review] == [("a.py", 9, "error"), ("a.py", 2, "info")]
    assert review[0]["inline"] is False  # line 9 is not part of the diff
    assert review[1]["inline"] is True


def test_graph_runs_all_agents_in_parallel_and_does_not_duplicate(monkeypatch):
    calls = []

    async def fake_llm(system_prompt, chunk):
        calls.append(system_prompt)
        assert "    2 +API_KEY" in chunk  # agents receive line-numbered diffs
        # Distinct message per agent (identical ones are intentionally collapsed by merge).
        return [{"file": "app/db.py", "line": 2, "severity": "error", "message": system_prompt.split(".")[0]}]

    monkeypatch.setattr(graph, "call_llm", fake_llm)
    state = asyncio.run(build_graph().ainvoke({"diff": DIFF, "patterns": [], "findings": []}))

    assert len(calls) == 4
    agents = sorted(f["agent"] for f in state["review"])
    assert agents == ["architecture", "security", "static_analysis", "style"]
    assert len(state["review"]) == 4  # merge output replaces, never appends to, the raw findings
    assert all(f["inline"] for f in state["review"])
