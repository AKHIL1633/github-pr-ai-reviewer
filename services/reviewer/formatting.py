SEVERITY_ICON = {"error": "🔴", "warning": "🟡", "info": "🔵"}
SEVERITIES = ("error", "warning", "info")
AGENTS = ("security", "static_analysis", "architecture", "style")


def _line(f: dict) -> int:
    try:
        return int(f.get("line") or 0)
    except (TypeError, ValueError):
        return 0


def is_inline(f: dict) -> bool:
    # The orchestrator marks whether the line is actually in the diff; GitHub rejects comments elsewhere.
    return bool(f.get("file")) and _line(f) > 0 and f.get("inline", True)


def _label(f: dict) -> str:
    severity = f.get("severity", "info")
    return f"{SEVERITY_ICON.get(severity, '🔵')} **{severity.upper()}** · `{f.get('agent', 'reviewer')}`"


def build_inline_comments(findings: list[dict]) -> list[dict]:
    return [
        {
            "path": f["file"],
            "line": _line(f),
            "side": "RIGHT",
            "body": f"{_label(f)}\n\n{f.get('message', '')}",
        }
        for f in findings
        if is_inline(f)
    ]


def build_summary(findings: list[dict], include_all: bool = False) -> str:
    """Review body: a severity-by-agent table plus any findings that can't be attached to a line.

    include_all lists every finding in the body (used when GitHub rejects the inline comments).
    """
    if not findings:
        return "## 🤖 AI Code Review\n\n✅ No issues found by the static analysis, security, style, and architecture agents."

    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEVERITIES}
    totals = " · ".join(f"{SEVERITY_ICON[s]} {counts[s]} {s}{'s' if counts[s] != 1 else ''}" for s in SEVERITIES)

    agents = list(AGENTS) + sorted({f.get("agent") for f in findings if f.get("agent") and f.get("agent") not in AGENTS})
    rows = []
    for agent in agents:
        per_agent = [f for f in findings if f.get("agent") == agent]
        if per_agent:
            cells = " | ".join(str(sum(1 for f in per_agent if f.get("severity") == s)) for s in SEVERITIES)
            rows.append(f"| {agent} | {cells} |")

    lines = [
        "## 🤖 AI Code Review",
        "",
        f"**{len(findings)} findings** — {totals}",
        "",
        "| Agent | 🔴 Error | 🟡 Warning | 🔵 Info |",
        "|---|:-:|:-:|:-:|",
        *rows,
    ]

    listed = findings if include_all else [f for f in findings if not is_inline(f)]
    if listed:
        title = "All findings" if include_all else "Findings outside the changed lines"
        lines += ["", f"<details><summary>{title} ({len(listed)})</summary>", ""]
        lines += [
            f"- {_label(f)} `{f.get('file', 'unknown')}:{f.get('line') or '?'}` — {f.get('message', '')}"
            for f in listed
        ]
        lines += ["", "</details>"]

    return "\n".join(lines)
