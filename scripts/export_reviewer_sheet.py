import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.golden_dataset import load_golden_dataset, review_rows, write_review_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a reviewer-ready golden dataset sheet.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output") / "golden_dataset_review_sheet.csv",
        help="CSV output path.",
    )
    args = parser.parse_args()

    dataset = load_golden_dataset()
    rows = review_rows(
        case for case in dataset["cases"] if case.get("review_status") in {"reviewer_ready", "expert_scored"}
    )
    write_review_csv(rows, args.output)
    print(f"Wrote reviewer sheet with {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
