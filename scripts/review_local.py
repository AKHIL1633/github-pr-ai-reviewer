"""Run the multi-agent review on a local diff, without GitHub, Postgres or Redis.

    git diff main | python scripts/review_local.py
    python scripts/review_local.py --diff changes.diff --json
    python scripts/review_local.py --pattern "Missing timeouts on HTTP calls"

Needs OPENAI_API_KEY (read from the environment or a .env file in the repo root).
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "orchestrator"))

COLORS = {"error": "\033[31m", "warning": "\033[33m", "info": "\033[36m"}
RESET, DIM, BOLD = "\033[0m", "\033[2m", "\033[1m"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#") and value:
            os.environ.setdefault(key.strip(), value.strip())


async def review(diff: str, patterns: list[str]) -> list[dict]:
    from graph import build_graph

    state = await build_graph().ainvoke({"diff": diff, "patterns": patterns, "findings": []})
    return state.get("review", [])


def print_report(findings: list[dict], elapsed: float, color: bool) -> None:
    c = (lambda code: code) if color else (lambda code: "")
    if not findings:
        print(f"{c(BOLD)}No issues found.{c(RESET)} ({elapsed:.1f}s)")
        return
    for f in findings:
        severity = f.get("severity", "info")
        where = f"{f.get('file')}:{f.get('line') or '?'}"
        print(f"{c(COLORS.get(severity, ''))}{severity.upper():<8}{c(RESET)}{c(BOLD)}{where}{c(RESET)} {c(DIM)}[{f.get('agent')}]{c(RESET)}")
        print(f"        {f.get('message')}\n")
    counts = {s: sum(f.get("severity") == s for f in findings) for s in ("error", "warning", "info")}
    print(f"{c(BOLD)}{len(findings)} findings{c(RESET)} — {counts['error']} errors, {counts['warning']} warnings, {counts['info']} info ({elapsed:.1f}s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--diff", type=Path, help="diff file to review (default: stdin)")
    parser.add_argument("--pattern", action="append", default=[], help="past repo issue to emphasise (repeatable)")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--fail-on", choices=["error", "warning"], help="exit 1 if any finding is at least this severe")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (export it or add it to .env)", file=sys.stderr)
        return 2

    diff = args.diff.read_text(encoding="utf-8") if args.diff else sys.stdin.read()
    if not diff.strip():
        print("Empty diff, nothing to review.", file=sys.stderr)
        return 0

    started = time.perf_counter()
    findings = asyncio.run(review(diff, args.pattern))
    elapsed = time.perf_counter() - started

    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        print_report(findings, elapsed, color=sys.stdout.isatty())

    if args.fail_on:
        blocking = {"error"} if args.fail_on == "error" else {"error", "warning"}
        return 1 if any(f.get("severity") in blocking for f in findings) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
