"""Convert the statute sources into clean text under resources/law/ (one-time import; re-run to refresh).

Inputs (download them first; nothing here fetches the network):
  <dir>/law_he.wiki    WikiSource raw wikitext of חוק צער בעלי חיים (ניסויים בבעלי חיים), התשנ"ד-1994
  <dir>/rules_he.wiki  WikiSource raw wikitext of כללי צער בעלי חיים (ניסויים בבעלי חיים), התשס"א-2001
  <dir>/law_en.pdf     Weizmann Institute PDF: private English translation of both, "correct as of May 30, 2007"

  python scripts/import_statute.py <dir>

Provenance and licences are written next to the files (resources/law/README.md keeps the human-readable
version). The statute text itself carries no copyright under Israeli law (Copyright Act 2007, s. 6);
WikiSource's markup layer is CC BY-SA; the English translation is private and its licence is unverified.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "resources" / "law"


def wiki_to_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        if line.startswith("{{ח:חתימות"):
            break  # the signatures block ends the legal text
        if line.startswith(("{{ח:התחלה", "{{ח:סיום", "{{ח:פתיח", "{{ח:מאגר", "{{ח:תיבה", "<div", "</div")):
            continue
        m = re.match(r"\{\{ח:קטע\d\|[^|}]*\|(.*)$", line)
        if m:
            title = re.sub(r"\{\{.*", "", m.group(1)).strip().rstrip("}").strip()  # drop any nested template (notes) from the title
            if title:
                lines.append(f"\n== {title} ==")
            continue
        if re.match(r"^\[\[קטגוריה:.*\]\]\s*$", line):  # WikiSource category links are not law text
            continue
        m = re.match(r"\{\{ח:סעיף\*?\|([^|}]*)\|([^|}]*)", line)
        if m:
            num, title = m.group(1).strip(), m.group(2).strip()
            lines.append(f"\nסעיף {num}" + (f": {title}" if title else ""))
            continue
        line = re.sub(r"\{\{ח:ת[^}]*\}\}", "", line)                 # paragraph/definition markers
        line = re.sub(r"\{\{ח:פנימי\|[^|}]*\|([^}]*)\}\}", r"\1", line)   # internal links -> text
        line = re.sub(r"\{\{ח:חיצוני\|[^|}]*\|([^}]*)\}\}", r"\1", line)  # external links -> text
        line = re.sub(r"\{\{ח:הערה\|[^}]*\}\}", "", line)
        line = re.sub(r"\{\{[^}]*\}\}", "", line)
        line = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", line)
        line = re.sub(r"<[^>]+>", "", line).replace("'''", "").strip()
        if line:
            lines.append(line)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def pdf_to_text(pdf: Path) -> str:
    raw = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True).stdout.decode("utf-8")
    out = []
    for line in raw.splitlines():
        if re.match(r"^Prevention of Cruelty to Animals - Law and Rules\s+\d+\s*$", line.strip()) or line.strip() == "\f":
            continue
        out.append(line.replace("\f", "").rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def main(src: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "statute-1994-he.txt").write_text(wiki_to_text((src / "law_he.wiki").read_text(encoding="utf-8")), encoding="utf-8")
    (OUT / "rules-2001-he.txt").write_text(wiki_to_text((src / "rules_he.wiki").read_text(encoding="utf-8")), encoding="utf-8")
    (OUT / "statute-and-rules-2007-en.txt").write_text(pdf_to_text(src / "law_en.pdf"), encoding="utf-8")
    for f in ("statute-1994-he.txt", "rules-2001-he.txt", "statute-and-rules-2007-en.txt"):
        p = OUT / f
        print(f"{f}: {len(p.read_text(encoding='utf-8'))} chars, {p.read_text(encoding='utf-8').count(chr(10))} lines")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
