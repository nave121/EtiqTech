"""Phase 2 eval gate: grounded vs ungrounded Layer 2 prompts over the golden pairs.

For every golden case (good/bad HTML pair with target_l2_themes), each target theme is
scored with the *blind* theme prompt (or, with --two-pass, the production blind → reconcile
flow, scoring the reconciled verdict) under two conditions — ungrounded (today's fixed law
prefix) and grounded (retrieved guidance sections with [Gn] refs) — using the same model,
temperature and seed-free sampling. Results are appended to a JSONL (resumable) and
--report renders the comparison into docs/benchmarks.md.

Metrics (per condition, overall and per theme):
  pair_acc   share of (case, theme) pairs where bad scored strictly lower than good
  bad_hit    share of bad variants scored <= 1 (deficiency caught)
  good_clean share of good variants scored >= 2 (no false alarm)
  json_ok    share of calls whose response parsed into a theme verdict
  cited      grounded only: share of verdicts whose rationale cites a [Gn] reference
  gap        mean(good score) - mean(bad score)
  sec        mean wall seconds per call

Only the fixture path, scores, timing and citation counts are stored — no protocol text.

  ETIQTECH_GROUNDING=1 python scripts/eval_grounding.py --model gemma4:e4b --limit 8
  python scripts/eval_grounding.py --model qwen3.5:35b --two-pass --out output/eval_grounding_2pass.jsonl
  python scripts/eval_grounding.py --report
"""
import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.golden_dataset import load_golden_dataset  # noqa: E402
from src.html_to_json import parse_html  # noqa: E402
from src.linter_renderer import lint  # noqa: E402
from src.llm_agent import (  # noqa: E402
    THEME_SPECS, _build_theme_prompt, _normalize_questions, _normalize_score, _normalize_theme_payload,
    _retrieve_grounding, parse_llm_json,
)
from src.llm_clients import call_llm  # noqa: E402
from src.retrieval import get_retriever  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CITATION = re.compile(r"\[G\d+\]")


def _score(text, theme):
    parsed = _parse(text)
    payload = parsed.get(theme) if isinstance(parsed, dict) else None
    if not isinstance(payload, dict):
        return None, False, 0
    s = _normalize_score(payload.get("score"), default=-1)
    cites = len(CITATION.findall(json.dumps(payload, ensure_ascii=False)))
    return (None if s == -1 else s), True, cites


def _parse(text):
    try:
        return parse_llm_json(text)
    except Exception:
        return None


def _reconcile_prompt(theme, instance, report, hits, blind_text):
    """Pass 2 exactly as production builds it (src/llm_agent.py, pass_name="reconcile")."""
    parsed = _parse(blind_text)
    payload = parsed.get(theme) if isinstance(parsed, dict) else None
    pass1_theme = _normalize_theme_payload(THEME_SPECS[theme], payload, fallback_rationale="LLM did not return the expected graded structure.")
    pass1_questions = _normalize_questions(parsed.get("questions")) if isinstance(parsed, dict) else []
    return _build_theme_prompt(theme, THEME_SPECS[theme], instance, report, pass_name="reconcile",
                               pass1_theme=pass1_theme, pass1_questions=pass1_questions, grounding_hits=hits or None)


def run(a):
    cases = [c for c in load_golden_dataset()["cases"] if c["dependencies"].get("current_expected_status") == "fully_testable"]
    if a.case_ids:
        cases = [c for c in cases if c["case_id"] in a.case_ids]
    cases = cases[: a.limit] if a.limit else cases
    conditions = a.conditions.split(",")
    out = Path(a.out)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add((r["case_id"], r["variant"], r["theme"], r["condition"], r.get("pass", "blind")))
    if "grounded" in conditions:
        os.environ["ETIQTECH_GROUNDING"] = "1"
        built = get_retriever().build_index()
        print(f"retrieval index: {'embedding' if built else 'LEXICAL FALLBACK (' + str(get_retriever().last_error) + ')'}", flush=True)
    total = sum(len(c["ground_truth"].get("target_l2_themes", []) if a.themes == "target" else THEME_SPECS) for c in cases) * 2 * len(conditions)
    n = 0
    with out.open("a") as fh:
        for c in cases:
            themes = c["ground_truth"].get("target_l2_themes", []) if a.themes == "target" else list(THEME_SPECS)
            for variant in ("good", "bad"):
                path = ROOT / (c["files"].get(f"{variant}_html") or c["files"][f"{variant}_json"])
                text = path.read_text(encoding="utf-8")
                instance = parse_html(text) if path.suffix == ".html" else json.loads(text)  # SYNTH/ADV cases are canonical JSON
                report = lint(instance, profile="default")
                for theme in themes:
                    if theme not in THEME_SPECS:
                        continue
                    for cond in conditions:
                        n += 1
                        key = (c["case_id"], variant, theme, cond, "reconcile" if a.two_pass else "blind")
                        if key in done:
                            continue
                        hits, notice = _retrieve_grounding(theme, instance) if cond == "grounded" else ([], None)
                        prompt = _build_theme_prompt(theme, THEME_SPECS[theme], instance, report, pass_name="blind", grounding_hits=hits or None)
                        rec = {"case_id": c["case_id"], "variant": variant, "theme": theme, "condition": cond, "model": a.model,
                               "target": theme in c["ground_truth"].get("target_l2_themes", []),
                               "n_grounding": len(hits), "grounding_method": (hits[0].method if hits else None), "notice": notice,
                               "prompt_chars": len(prompt), "pass": key[-1]}
                        t0 = time.time()
                        try:
                            text = call_llm(prompt, model=a.model, temperature=0.2)
                            rec["score"], rec["json_ok"], rec["citations"] = _score(text, theme)
                            rec["chars"] = len(text)
                            if a.two_pass:
                                rec["blind_score"], rec["blind_json_ok"] = rec["score"], rec["json_ok"]
                                rec["blind_seconds"] = round(time.time() - t0, 1)
                                prompt2 = _reconcile_prompt(theme, instance, report, hits, text)
                                rec["prompt2_chars"] = len(prompt2)
                                text = call_llm(prompt2, model=a.model, temperature=0.2)
                                rec["score"], rec["json_ok"], rec["citations"] = _score(text, theme)
                                rec["chars"] = len(text)
                        except Exception as e:
                            rec.update(score=None, json_ok=False, citations=0, chars=None, llm_error=f"{type(e).__name__}")
                        rec["seconds"] = round(time.time() - t0, 1)
                        fh.write(json.dumps(rec) + "\n"); fh.flush()
                        print(f"[{n}/{total}] {c['case_id']} {variant} {theme} {cond} score={rec['score']} json={rec['json_ok']} cites={rec.get('citations')} {rec['seconds']}s", flush=True)


def summarize(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["condition"]].append(r)
    table = {}
    for cond, rs in by.items():
        pairs = defaultdict(dict)
        for r in rs:
            pairs[(r["case_id"], r["theme"])][r["variant"]] = r["score"]
        complete = [p for p in pairs.values() if p.get("good") is not None and p.get("bad") is not None]
        good = [r["score"] for r in rs if r["variant"] == "good" and r["score"] is not None]
        bad = [r["score"] for r in rs if r["variant"] == "bad" and r["score"] is not None]
        table[cond] = {
            "calls": len(rs),
            "json_ok": sum(r["json_ok"] for r in rs) / len(rs),
            "pair_acc": (sum(p["bad"] < p["good"] for p in complete) / len(complete)) if complete else float("nan"),
            "bad_hit": (sum(s <= 1 for s in bad) / len(bad)) if bad else float("nan"),
            "good_clean": (sum(s >= 2 for s in good) / len(good)) if good else float("nan"),
            "gap": (statistics.mean(good) - statistics.mean(bad)) if good and bad else float("nan"),
            "cited": (sum(r.get("citations", 0) > 0 for r in rs) / len(rs)) if cond == "grounded" else None,
            "sec": statistics.mean(r["seconds"] for r in rs),
            "n_pairs": len(complete),
        }
    return table


def report(a):
    rows = [json.loads(l) for l in Path(a.out).read_text().splitlines()]
    if not rows:
        sys.exit("no results yet")
    passes = sorted({r.get("pass", "blind") for r in rows})
    if len(passes) > 1:
        sys.exit(f"{a.out} mixes passes {passes}; use one --out per mode")
    flow = "two-pass (blind → reconcile), reconciled verdict scored" if passes == ["reconcile"] else "blind pass only"
    overall = summarize(rows)
    per_theme = {t: summarize([r for r in rows if r["theme"] == t]) for t in sorted({r["theme"] for r in rows})}
    models = sorted({r["model"] for r in rows})
    lines = [f"## Grounded vs ungrounded Layer 2 — {date.today().isoformat()}", "",
             f"Model: `{', '.join(models)}` · {flow} · temperature 0.2 · cases: {len({r['case_id'] for r in rows})} golden pairs · "
             f"themes: target_l2_themes per case · retrieval: k=5 over `resources/corpus/guidance_il.jsonl`", "",
             "| condition | pairs | pair_acc | bad_hit | good_clean | gap | json_ok | cited | sec/call |", "|---|---|---|---|---|---|---|---|---|"]
    def row(name, m):
        cited = "—" if m["cited"] is None else f"{m['cited']:.0%}"
        return f"| {name} | {m['n_pairs']} | {m['pair_acc']:.0%} | {m['bad_hit']:.0%} | {m['good_clean']:.0%} | {m['gap']:+.2f} | {m['json_ok']:.0%} | {cited} | {m['sec']:.0f} |"
    for cond in ("ungrounded", "grounded"):
        if cond in overall:
            lines.append(row(cond, overall[cond]))
    lines += ["", "Per theme:", "", "| theme | condition | pairs | pair_acc | bad_hit | good_clean | gap | cited |", "|---|---|---|---|---|---|---|---|"]
    for t, m in per_theme.items():
        for cond in ("ungrounded", "grounded"):
            if cond in m:
                x = m[cond]; cited = "—" if x["cited"] is None else f"{x['cited']:.0%}"
                lines.append(f"| {t} | {cond} | {x['n_pairs']} | {x['pair_acc']:.0%} | {x['bad_hit']:.0%} | {x['good_clean']:.0%} | {x['gap']:+.2f} | {cited} |")
    lines += ["", "pair_acc = bad variant scored strictly below good on the same theme; bad_hit = bad scored <= 1; "
              "good_clean = good scored >= 2; gap = mean(good) - mean(bad); cited = grounded rationales citing a [Gn] source.", ""]
    text = "\n".join(lines)
    print(text)
    if a.report_path:
        p = Path(a.report_path)
        head = p.read_text(encoding="utf-8") if p.exists() else "# Benchmarks\n\nResults produced by `scripts/eval_grounding.py` and `scripts/ab_presence_penalty.py`. Every table names its model, sample and settings; treat anything run on a model other than the production default as directional.\n\n"
        p.write_text(head + text + "\n", encoding="utf-8")
        print(f"appended to {p}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:35b"))
    ap.add_argument("--limit", type=int, default=0, help="first N testable cases (0 = all)")
    ap.add_argument("--case-ids", nargs="*")
    ap.add_argument("--themes", choices=["target", "all"], default="target")
    ap.add_argument("--conditions", default="ungrounded,grounded")
    ap.add_argument("--two-pass", action="store_true", help="run blind → reconcile like production and score the reconciled verdict")
    ap.add_argument("--out", default="output/eval_grounding.jsonl")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--report-path", default="docs/benchmarks.md")
    a = ap.parse_args()
    report(a) if a.report else run(a)
