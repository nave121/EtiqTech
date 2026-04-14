import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.golden_dataset import collect_coverage, load_golden_dataset, validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize the golden dataset coverage.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    dataset = load_golden_dataset()
    errors = validate_dataset(dataset)
    coverage = collect_coverage(dataset["cases"])
    payload = {"validation_errors": errors, "coverage": coverage}

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote golden dataset report to {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
