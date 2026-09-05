"""Byte-level equivalence check for the linter split (docs/dev-log/linter-split-plan.md §4).

  python scripts/lint_snapshot.py build/lint-snapshot   # take (from the pre-split tree only)
  python scripts/lint_snapshot.py build/lint-current && diff -r build/lint-snapshot build/lint-current

Every fixture under examples/ x both profiles -> one JSON per report with generated_at removed,
sort_keys=False (key order is frozen too). Runs with the default jurisdiction pack.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["ETIQTECH_JURISDICTION"] = ""
from src.html_to_json import parse_html  # noqa: E402
from src.linter_renderer import lint  # noqa: E402

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "build/lint-current")
out.mkdir(parents=True, exist_ok=True)
n = 0
for f in sorted(pathlib.Path("examples").rglob("*.html")):
    inst = parse_html(f.read_text(encoding="utf-8"))
    for prof in ("default", "strict_law"):
        rep = lint(inst, profile=prof)
        rep.pop("generated_at", None)
        name = str(f.relative_to("examples")).replace("/", "__") + f".{prof}.json"
        (out / name).write_text(json.dumps(rep, ensure_ascii=False, sort_keys=False, indent=1), encoding="utf-8")
        n += 1
print(f"{n} reports written to {out}")
