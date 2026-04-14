"""
Evaluate known good/bad example sets and collect lint (and optional LLM) analytics.

Usage examples:

    # Lint only, default profile, summarize known good/bad sets
    python scripts/eval_cases.py

    # Lint with strict law profile
    python scripts/eval_cases.py --profile strict_law

    # Include LLM verification (requires running Ollama/OpenAI provider)
    python scripts/eval_cases.py --with-llm --llm-mode multi

    # Limit number of files per set for quicker runs
    python scripts/eval_cases.py --limit-good 5 --limit-bad 5

    # Run the LLM in the softer committee stance
    python scripts/eval_cases.py --with-llm --llm-stance committee
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path when running as a script.
REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.html_to_json import parse_html
from src.linter_renderer import lint
from src.llm_agent import run_verification

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
DEFAULT_GOOD_DIR = EXAMPLES_DIR / "known-good"
DEFAULT_BAD_DIR = EXAMPLES_DIR / "known-bad"


def _analyze_dir(
    path: Path,
    profile: str,
    limit: Optional[int],
    with_llm: bool,
    llm_mode: str,
    llm_stance: str,
) -> Dict[str, Any]:
    files = sorted(path.glob("*.html"))
    if limit is not None:
        files = files[:limit]

    results: List[Dict[str, Any]] = []
    ref_counter: Counter = Counter()
    statuses: Counter = Counter()

    for f in files:
        try:
            html = f.read_text(encoding="utf-8")
            instance = parse_html(html)
            report = lint(instance, profile=profile)

            failing_refs = [
                c.get("reference") for c in report.get("checklist", []) if c.get("status") == "fail"
            ]
            for r in failing_refs:
                if r:
                    ref_counter[r] += 1

            llm_verdict = None
            if with_llm:
                try:
                    llm_verdict = run_verification(
                        instance,
                        report,
                        mode=llm_mode,
                        stance=llm_stance,
                    )
                except Exception as exc:  # noqa: BLE001
                    llm_verdict = {"error": str(exc)}

            results.append(
                {
                    "file": f.name,
                    "status": report.get("status"),
                    "errors": report.get("errors"),
                    "warnings": report.get("warnings"),
                    "failing_refs": failing_refs,
                    "llm_verdict": llm_verdict,
                }
            )
            statuses[report.get("status")] += 1
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "file": f.name,
                    "status": "CRASH",
                    "errors": None,
                    "warnings": None,
                    "failing_refs": [],
                    "llm_verdict": {"error": str(exc)},
                }
            )
            statuses["CRASH"] += 1

    summary = {
        "path": str(path),
        "profile": profile,
        "files": len(results),
        "status_counts": dict(statuses),
        "top_failing_refs": ref_counter.most_common(15),
    }
    return {"summary": summary, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint (and optionally LLM-verify) known examples.")
    parser.add_argument("--good-dir", type=Path, default=DEFAULT_GOOD_DIR, help="Directory of good examples")
    parser.add_argument("--bad-dir", type=Path, default=DEFAULT_BAD_DIR, help="Directory of bad examples")
    parser.add_argument("--profile", choices=["default", "strict_law"], default="default", help="Lint profile")
    parser.add_argument("--limit-good", type=int, default=None, help="Limit number of good files")
    parser.add_argument("--limit-bad", type=int, default=None, help="Limit number of bad files")
    parser.add_argument("--with-llm", action="store_true", help="Run LLM verification (requires provider)")
    parser.add_argument(
        "--llm-mode",
        choices=["multi", "single"],
        default="multi",
        help="LLM verification mode (multi = per-theme prompts, single = legacy mega prompt)",
    )
    parser.add_argument(
        "--llm-stance",
        choices=["law", "committee"],
        default="law",
        help="LLM stance: strict law vs. softer committee-approved weighting.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional path to write JSON report")

    args = parser.parse_args()

    good_report = _analyze_dir(
        args.good_dir,
        args.profile,
        args.limit_good,
        args.with_llm,
        args.llm_mode,
        args.llm_stance,
    )
    bad_report = _analyze_dir(
        args.bad_dir,
        args.profile,
        args.limit_bad,
        args.with_llm,
        args.llm_mode,
        args.llm_stance,
    )

    out = {"good": good_report, "bad": bad_report}
    out_str = json.dumps(out, ensure_ascii=False, indent=2)

    if args.output:
        args.output.write_text(out_str, encoding="utf-8")
        print(f"Wrote report to {args.output}")
    else:
        print(out_str)


if __name__ == "__main__":
    main()
