import argparse
import sys
from pathlib import Path
from collections import Counter
from src.html_to_json import parse_html
from src.linter_renderer import lint

def main():
    parser = argparse.ArgumentParser(description="Batch analyze HTML export files.")
    parser.add_argument("input_dir", type=str, help="Directory containing .html files")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit with non-zero status if any file fails")
    parser.add_argument("--verbose", action="store_true", help="Print all checks, not just errors")
    parser.add_argument(
        "--profile",
        type=str,
        choices=["default", "strict_law"],
        default="default",
        help="Linting profile to use (default or strict_law).",
    )
    args = parser.parse_args()
    
    input_path = Path(args.input_dir)
    if not input_path.exists():
        print(f"Error: Directory {input_path} not found.")
        sys.exit(1)
        
    files = sorted(list(input_path.glob("*.html")))
    if not files:
        print(f"No HTML files found in {input_path}")
        sys.exit(0)

    print(f"Found {len(files)} files in {input_path}")
    
    results = []
    all_errors = Counter()
    failures = 0
    
    for f in files:
        try:
            html_content = f.read_text(encoding="utf-8")
            instance = parse_html(html_content)
            report = lint(instance, profile=args.profile)
            
            status = report["status"]
            errors = [c["message"] for c in report["checklist"] if c["status"] == "fail"]
            
            if status == "fail":
                failures += 1
                
            results.append({
                "file": f.name,
                "status": status,
                "error_count": len(errors),
                "errors": errors
            })
            
            for e in errors:
                all_errors[e] += 1
                
        except Exception as e:
            print(f"CRASH processing {f.name}: {e}")
            results.append({
                "file": f.name,
                "status": "CRASH",
                "error_count": 0,
                "errors": [str(e)]
            })
            failures += 1

    # Reporting
    print(f"\n--- Summary ({len(files)} files) ---")
    print(f"Passed: {len(files) - failures}")
    print(f"Failed: {failures}")
    
    if all_errors:
        print("\n--- Top Errors ---")
        for err, count in all_errors.most_common(10):
            print(f"[{count}] {err}")
        
    if failures > 0:
        print("\n--- Detailed Failures ---")
        for r in results:
            if r["status"] != "pass":
                print(f"\n{r['file']} ({r['error_count']} errors):")
                for e in r['errors']:
                    print(f"  - {e}")
    else:
        print("\nAll files passed!")

    if args.fail_on_error and failures > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
