"""Measure review quality against labelled cases with seeded bugs.

Each file in eval/cases/ is a small source file. Lines carrying a `# expect: <agent>`
comment are known issues; the markers are stripped before the code is turned into a
new-file diff and reviewed, so the model never sees the labels.

    python scripts/benchmark.py                 # run all cases, print a report
    python scripts/benchmark.py --min-recall 0.8  # fail (exit 1) below 80% recall, for CI
    python scripts/benchmark.py --dry-run       # show parsed cases, no API calls

Metrics
  recall           seeded issues that got a warning/error within ±2 lines
  false positives  warning/error findings on clean_code.py (should be 0)
  noise            warning/error findings per case that match no seeded issue
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_local import ROOT, load_dotenv, review  # noqa: E402

CASES_DIR = ROOT / "eval" / "cases"
MARKER = re.compile(r"\s*#\s*expect:\s*(\w+)\s*$")
LINE_TOLERANCE = 2
BLOCKING = {"warning", "error"}


def load_case(path: Path) -> dict:
    code_lines, expected = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        marker = MARKER.search(line)
        if marker:
            expected.append({"line": number, "agent": marker.group(1)})
            line = line[: marker.start()]
        code_lines.append(line)

    file = f"src/{path.name}"
    diff = "\n".join([
        f"diff --git a/{file} b/{file}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{file}",
        f"@@ -0,0 +1,{len(code_lines)} @@",
        *(f"+{line}" for line in code_lines),
    ]) + "\n"
    return {"name": path.stem, "file": file, "diff": diff, "expected": expected}


def score_case(case: dict, findings: list[dict]) -> dict:
    blocking = [f for f in findings if f.get("severity") in BLOCKING and f.get("file") == case["file"]]
    caught, matched = [], set()
    for issue in case["expected"]:
        hits = [i for i, f in enumerate(blocking) if abs((f.get("line") or -99) - issue["line"]) <= LINE_TOLERANCE]
        caught.append(bool(hits))
        matched.update(hits)
    return {
        "name": case["name"],
        "expected": len(case["expected"]),
        "caught": sum(caught),
        "by_agent": [(issue["agent"], hit) for issue, hit in zip(case["expected"], caught)],
        "noise": len(blocking) - len(matched),
        "findings": len(findings),
    }


async def run(cases: list[dict], concurrency: int) -> list[tuple[dict, list[dict], float]]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case):
        async with semaphore:
            started = time.perf_counter()
            findings = await review(case["diff"], [])
            return case, findings, time.perf_counter() - started

    return await asyncio.gather(*(one(c) for c in cases))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-recall", type=float, default=0.0)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, help="write raw results as JSON")
    args = parser.parse_args()

    cases = [load_case(p) for p in sorted(CASES_DIR.glob("*.py"))]
    if args.dry_run:
        for case in cases:
            print(f"{case['name']:<22} expects {[(e['line'], e['agent']) for e in case['expected']]}")
        return 0

    load_dotenv(ROOT / ".env")
    results = asyncio.run(run(cases, args.concurrency))
    scores = [score_case(case, findings) for case, findings, _ in results]
    latencies = sorted(elapsed for _, _, elapsed in results)

    print(f"{'case':<22}{'caught':>8}{'noise':>7}{'findings':>10}{'latency':>9}")
    for score, (_, _, elapsed) in zip(scores, results):
        print(f"{score['name']:<22}{score['caught']:>4}/{score['expected']:<3}{score['noise']:>7}{score['findings']:>10}{elapsed:>8.1f}s")

    expected = sum(s["expected"] for s in scores)
    caught = sum(s["caught"] for s in scores)
    recall = caught / expected if expected else 1.0
    false_positives = sum(s["noise"] for s in scores if s["expected"] == 0)
    by_agent: dict[str, list[bool]] = {}
    for s in scores:
        for agent, hit in s["by_agent"]:
            by_agent.setdefault(agent, []).append(hit)

    print(f"\nRecall: {recall:.0%} ({caught}/{expected} seeded issues)")
    for agent, hits in sorted(by_agent.items()):
        print(f"  {agent:<18}{sum(hits)}/{len(hits)}")
    print(f"False positives on clean code: {false_positives}")
    print(f"Median latency per PR: {latencies[len(latencies) // 2]:.1f}s")

    if args.output:
        args.output.write_text(json.dumps(
            [{"case": c["name"], "findings": f, "seconds": t} for c, f, t in results], indent=2
        ))

    if recall < args.min_recall:
        print(f"Recall {recall:.0%} is below the required {args.min_recall:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
