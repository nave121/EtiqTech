"""A/B harness for OLLAMA_PRESENCE_PENALTY on the golden fixtures (P0.3).

Runs the Layer 2 *blind* theme prompt for each (protocol, theme, penalty, repeat)
and records JSON-parse success, the raw theme score, and wall time. Results are
appended to a JSONL file so a run can be resumed; --summarize prints the table
that drives the default. Protocol content goes only to the configured local
Ollama; the JSONL stores the fixture *path*, scores and timings — no protocol text.

  python scripts/ab_presence_penalty.py --model qwen3.6:27b-mlx --repeats 2
  python scripts/ab_presence_penalty.py --summarize
"""
import argparse
import glob
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.html_to_json import parse_html  # noqa: E402
from src.linter_renderer import lint  # noqa: E402
from src.llm_agent import THEME_SPECS, _build_theme_prompt, _normalize_score, parse_llm_json  # noqa: E402
from src.llm_clients import call_llm  # noqa: E402

DEFAULT_THEMES = ["three_Rs_alternatives", "N_and_justification", "severity_monitoring_analgesia", "writing_quality"]
DEFAULT_PROTOCOLS = sorted(glob.glob("examples/known-good/good_IL-00[1-3]*.html")) + sorted(
    glob.glob("examples/known-bad/bad_IL-00[1-3]*-2000.html")
)


def run(args):
    out = Path(args.out)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add((r["protocol"], r["theme"], r["penalty"], r["repeat"]))
    penalties = [float(p) for p in args.penalties.split(",")]
    themes = args.themes.split(",")
    protocols = args.protocols or DEFAULT_PROTOCOLS
    total = len(protocols) * len(themes) * len(penalties) * args.repeats
    n = 0
    with out.open("a") as fh:
        for path in protocols:
            instance = parse_html(Path(path).read_text(encoding="utf-8"))
            report = lint(instance, profile="default")
            expected = "good" if "/known-good/" in path or "/good" in path else "bad"
            for theme in themes:
                prompt = _build_theme_prompt(theme, THEME_SPECS[theme], instance, report, pass_name="blind")
                for penalty in penalties:
                    for rep in range(args.repeats):
                        n += 1
                        key = (path, theme, penalty, rep)
                        if key in done:
                            continue
                        os.environ["OLLAMA_PRESENCE_PENALTY"] = str(penalty)
                        t0 = time.time()
                        rec = {"protocol": path, "expected": expected, "theme": theme, "penalty": penalty, "repeat": rep,
                               "model": args.model}
                        try:
                            text = call_llm(prompt, model=args.model, temperature=0.2)
                            rec["chars"] = len(text)
                            try:
                                parsed = parse_llm_json(text)
                                payload = parsed.get(theme) if isinstance(parsed, dict) else None
                                rec["parse_ok"] = isinstance(payload, dict)
                                raw_score = payload.get("score") if isinstance(payload, dict) else None
                                rec["raw_score"] = repr(raw_score)[:20]  # a grade token, never protocol text
                                norm = _normalize_score(raw_score, default=-1)  # the app's own tolerant parser
                                rec["score"] = norm if norm != -1 else None
                                rec["has_sub_questions"] = bool(isinstance(payload, dict) and payload.get("sub_questions"))
                            except Exception as e:  # parse failure is a measured outcome, not a crash
                                rec["parse_ok"] = False
                                rec["score"] = None
                                rec["parse_error"] = type(e).__name__
                        except Exception as e:
                            rec["llm_error"] = f"{type(e).__name__}: {str(e)[:120]}"
                            rec["parse_ok"] = False
                            rec["score"] = None
                        rec["seconds"] = round(time.time() - t0, 1)
                        fh.write(json.dumps(rec) + "\n")
                        fh.flush()
                        print(f"[{n}/{total}] {Path(path).name} {theme} pp={penalty} r{rep} parse_ok={rec['parse_ok']} score={rec['score']} {rec['seconds']}s", flush=True)


def summarize(args):
    rows = [json.loads(l) for l in Path(args.out).read_text().splitlines()]
    by_pen = defaultdict(list)
    for r in rows:
        by_pen[r["penalty"]].append(r)
    print(f"{'penalty':>8} {'n':>4} {'parse_fail':>10} {'no_score':>8} {'flip_rate':>9} {'good_mean':>9} {'bad_mean':>8} {'gap':>5} {'sec':>6}")
    for pen in sorted(by_pen):
        rs = by_pen[pen]
        n = len(rs)
        parse_fail = sum(not r["parse_ok"] for r in rs) / n
        no_score = sum(r["score"] is None for r in rs) / n
        # stability: same protocol+theme, different repeats -> did the score change?
        groups = defaultdict(list)
        for r in rs:
            if r["score"] is not None:
                groups[(r["protocol"], r["theme"])].append(r["score"])
        pairs = [g for g in groups.values() if len(g) >= 2]
        flips = sum(len(set(g)) > 1 for g in pairs) / len(pairs) if pairs else float("nan")
        good = [r["score"] for r in rs if r["expected"] == "good" and r["score"] is not None]
        bad = [r["score"] for r in rs if r["expected"] == "bad" and r["score"] is not None]
        gm = statistics.mean(good) if good else float("nan")
        bm = statistics.mean(bad) if bad else float("nan")
        secs = statistics.mean(r["seconds"] for r in rs)
        print(f"{pen:>8} {n:>4} {parse_fail:>10.0%} {no_score:>8.0%} {flips:>9.0%} {gm:>9.2f} {bm:>8.2f} {gm-bm:>5.2f} {secs:>6.1f}")
    print("\nflip_rate = share of (protocol, theme) pairs whose score differed between repeats (lower = more stable)")
    print("gap = mean score on known-good minus known-bad (higher = better discrimination)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:35b"))
    ap.add_argument("--penalties", default="1.5,0,0.5")
    ap.add_argument("--themes", default=",".join(DEFAULT_THEMES))
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--protocols", nargs="*")
    ap.add_argument("--out", default="output/ab_presence_penalty.jsonl")
    ap.add_argument("--summarize", action="store_true")
    a = ap.parse_args()
    summarize(a) if a.summarize else run(a)
