"""Sectionize the Israeli national guidance (EN translation + HE original) into retrieval units.

Output: resources/corpus/guidance_il.jsonl — one JSON record per chunk, schema per the
handoff brief (id, url, title, doc_type, species, text, license, retrieved_at) plus
lang, section_path, source. Deterministic: same inputs -> same file, so the corpus is
committed and reviewable. Re-run after editing the sources.

  python scripts/build_law_corpus.py            # writes resources/corpus/guidance_il.jsonl
  python scripts/build_law_corpus.py --check    # exit 1 if the committed file is stale

Hebrew comes from `pdftotext` on the guidance PDF (logical order). The older
resources/law/the_law.txt is a word-reversed extraction of the same PDF and is not used.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAW_DIR = ROOT / "resources" / "law"
EN_SRC = LAW_DIR / "the_law-english_translation.txt"
HE_PDF = LAW_DIR / "national-guidance-2025-he.pdf"
HE_TXT = LAW_DIR / "national-guidance-2025-he.txt"  # clean extraction, committed
OUT = ROOT / "resources" / "corpus" / "guidance_il.jsonl"

DOC_TITLE_EN = "Israeli National Council for Animal Experimentation — guidance for the request form (2025)"
DOC_TITLE_HE = "המועצה לניסויים בבעלי חיים — הנחיות כלליות למילוי שדות טופס הבקשה (עדכון 2025)"
LICENSE = "Israeli government publication; redistribution terms unverified — cite, do not reprint"
MAX_CHARS = 1600  # ~400 tokens; k=5-8 chunks stays well inside the Layer 2 budget

_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩]")
_HE_HEADING = re.compile(r"^(תת סעיף|חלק [א-ת]|סעיף \d|הקדמה|כללי|דברי הסבר)")
_HE_PAGE_MARK = re.compile(r"^[–\-—\s]*עמוד[–\-—\s]*\d+[–\-—\s]*$")
MIN_SECTION_CHARS = 120  # smaller Hebrew fragments are merged into the preceding section


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _windows(paragraphs, max_chars=MAX_CHARS):
    """Greedy paragraph packing; a single oversize paragraph is split at sentence ends."""
    out, cur = [], ""
    for p in paragraphs:
        if len(p) > max_chars:
            if cur:
                out.append(cur); cur = ""
            sentences = re.split(r"(?<=[.!?:;])\s+", p)  # ';' too: statute definitions are one long sentence
            for s in sentences:
                if len(cur) + len(s) + 1 > max_chars and cur:
                    out.append(cur); cur = ""
                cur = f"{cur} {s}".strip()
            continue
        if len(cur) + len(p) + 1 > max_chars and cur:
            out.append(cur); cur = ""
        cur = f"{cur}\n{p}".strip()
    if cur:
        out.append(cur)
    return out


def sectionize_en(text: str):
    """Markdown-ish headings (#, ##). Consecutive heading lines are one wrapped heading."""
    sections, heading, buf, parents = [], None, [], []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("#"):
            if heading is not None:
                sections.append((list(parents), heading, buf))
            level = len(line) - len(line.lstrip("#"))
            title = line.lstrip("#").strip()
            # A heading wrapped over two source lines: the first ends mid-phrase, or the
            # second is a short tail that is not itself a "Part"/"Subsection" heading.
            while True:
                j = i + 1
                while j < len(lines) and not lines[j].strip():  # wrapped headings may be separated by a blank line
                    j += 1
                if j >= len(lines) or not lines[j].startswith("#"):
                    break
                if len(lines[j]) - len(lines[j].lstrip("#")) != level:
                    break  # a sub-heading is a new section, never a continuation
                tail = lines[j].lstrip("#").strip()
                dangling = title.rstrip().endswith((" in", " and", " of", " -", " –", ",", " for", " the"))
                short_tail = len(tail.split()) <= 3 and not tail.startswith(("Part", "Subsection", "[")) and not tail.endswith(":")
                if not (dangling or short_tail):
                    break
                i = j
                title += " " + tail
            parents = parents[: max(level - 1, 0)]
            heading = title
            buf = []
            if level == 1:
                parents = [title]
            else:
                parents = parents[:1] + [title]
        elif heading is not None:
            buf.append(line)
        i += 1
    if heading is not None:
        sections.append((list(parents), heading, buf))
    return sections


_SWAP_PARENS = str.maketrans("()", ")(")


_PROTECT = re.compile(r"https?://\S+|[A-Za-z][A-Za-z0-9@._/'-]*(?:\s+[A-Za-z][A-Za-z0-9@._/'-]*)*")


def _normalize_he(line: str) -> str:
    """pdftotext emits visual-order artifacts in RTL text: mirrored parentheses, punctuation
    glued to the following word, digits glued to letters. Fix the common ones — but leave
    URLs and Latin spans (EURL ECVAM, e-mail addresses) untouched: the rules are for Hebrew."""
    keep: list = []
    line = line.translate(_SWAP_PARENS)
    # after the swap, a visual ')(Latin' has become '()Latin'; the logical form is '(Latin)'
    line = re.sub(r"\(\)([A-Za-z][A-Za-z0-9 ._'-]*[A-Za-z0-9])", r"(\1)", line)

    def _stash(m):
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"
    line = _PROTECT.sub(_stash, line)
    line = re.sub(r"\s+([.,;:!?])", r"\1", line)           # 'בלבד ,והשיקול' -> 'בלבד,והשיקול'
    line = re.sub(r"([.,;:!?])(?=[^\s\d.,;:!?)\]\x00])", r"\1 ", line)  # then one space after
    line = re.sub(r"(\d)(?=[א-ת])", r"\1 ", line)            # '1994חוקקה' -> '1994 חוקקה'
    line = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], line)
    return re.sub(r"\s{2,}", " ", line).strip()


def sectionize_he(text: str):
    text = _BIDI.sub("", text)
    lines = [_normalize_he(l) for l in text.splitlines()]
    sections, heading, buf = [], "הקדמה", []
    for line in lines:
        if not line or line.isdigit() or _HE_PAGE_MARK.match(line) or set(line) <= set("—-–_ "):
            continue  # page numbers / running page marks / rules
        is_heading = _HE_HEADING.match(line) or (len(line) <= 45 and not line.endswith((".", ",", ";")) and not line[:1].isdigit())
        if is_heading:
            if buf:
                sections.append(([heading], heading, buf))
            heading, buf = line, []
        else:
            buf.append(line)
    if buf:
        sections.append(([heading], heading, buf))
    # merge fragments too small to stand alone into their predecessor
    merged = []
    for sec in sections:
        if merged and sum(len(l) for l in sec[2]) < MIN_SECTION_CHARS:
            merged[-1][2].extend([sec[1]] + sec[2])
        else:
            merged.append([sec[0], sec[1], list(sec[2])])
    return [tuple(m) for m in merged]


def _records(sections, lang, doc_title, source):
    recs = []
    used = set()
    source_sha = hashlib.sha256((LAW_DIR / source).read_bytes()).hexdigest()[:12]
    for parents, heading, buf in sections:
        paragraphs, cur = [], []
        for l in buf:
            if l.strip():
                cur.append(l.strip())
            elif cur:
                paragraphs.append(" ".join(cur)); cur = []
        if cur:
            paragraphs.append(" ".join(cur))
        body = "\n".join(paragraphs).strip()
        if len(body) < 40:  # a bare heading with no content is not a retrievable unit
            continue
        chunks = _windows(paragraphs)
        for n, chunk in enumerate(chunks, 1):
            if lang == "en":
                base = _slug(" ".join(parents)) if len(parents) > 1 and heading.lower() == "general" else _slug(heading)
            else:
                base = hashlib.sha1(chunk.encode("utf-8")).hexdigest()[:8]  # stable unless this chunk's text changes
            rid = f"il-guidance-{lang}-{base}" + (f"-{n}" if len(chunks) > 1 else "")
            k = 2
            while rid in used:  # repeated headings ("General") get a stable ordinal suffix
                rid = f"il-guidance-{lang}-{base}-{k}" + (f"-{n}" if len(chunks) > 1 else "")
                k += 1
            used.add(rid)
            recs.append({
                "id": rid,
                "url": f"etiqtech://resources/law/{source}#{rid}",  # no public URL known for this PDF; local anchor
                "title": f"{doc_title} — {' › '.join(parents) if parents else heading}",
                "doc_type": "guidance_section",
                "jurisdiction": "IL",
                "lang": lang,
                "section_path": parents if parents else [heading],
                "species": [],  # guidance is species-agnostic; NORINA records will carry species
                "text": chunk,
                "license": LICENSE,
                "source": source,
                "source_sha256": source_sha,  # provenance that moves with the file, unlike a hand-bumped date
                "retrieved_at": "2026-09-05",  # date the source files were last (re)obtained; bump when they are
            })
    return recs


def extract_hebrew() -> str:
    if HE_TXT.exists():
        return HE_TXT.read_text(encoding="utf-8")
    if shutil.which("pdftotext") is None:
        sys.exit("pdftotext (poppler) not found and no cached national-guidance-2025-he.txt")
    raw = subprocess.run(["pdftotext", str(HE_PDF), "-"], check=True, capture_output=True).stdout.decode("utf-8")
    clean = _BIDI.sub("", raw)
    HE_TXT.write_text(clean, encoding="utf-8")
    return clean


# ---------------------------------------------------------------------------
# The statute and the rules (imported by scripts/import_statute.py). One record per section.
# ---------------------------------------------------------------------------
STATUTE = {
    "statute-1994-he.txt": ("il-law-1994", "he", "חוק צער בעלי חיים (ניסויים בבעלי חיים), התשנ״ד–1994",
                            "Statute text: no copyright under Israeli Copyright Act 2007 s.6; WikiSource markup layer CC BY-SA"),
    "rules-2001-he.txt": ("il-rules-2001", "he", "כללי צער בעלי חיים (ניסויים בבעלי חיים), התשס״א–2001",
                          "Rules text: no copyright under Israeli Copyright Act 2007 s.6; WikiSource markup layer CC BY-SA"),
}
STATUTE_EN = "statute-and-rules-2007-en.txt"
STATUTE_EN_LICENSE = "Private English translation (Weizmann Institute veterinary resources, correct as of 30 May 2007); licence not stated — used for grounding, redistribution terms unverified"


def sectionize_statute_he(text: str):
    """'== chapter ==' headers and 'סעיף N: title' section lines from import_statute.py."""
    sections, chapter, current, buf = [], "", None, []
    for line in text.splitlines():
        m = re.match(r"^== (.*) ==$", line)
        if m:
            chapter = m.group(1).strip()
            continue
        m = re.match(r"^סעיף ([^\s:]+):?\s*(.*)$", line)
        if m:
            if current:
                sections.append((current[0], current[1], current[2], buf))
            current, buf = (m.group(1), (m.group(2) or "").strip(), chapter), []
            continue
        if current and line.strip():
            buf.append(line.strip())
    if current:
        sections.append((current[0], current[1], current[2], buf))
    return sections


def sectionize_statute_en(text: str):
    """Numbered sections ('N.  text') under CHAPTER headers; the Rules start at their title page."""
    sections, chapter, part, current, buf, max_law = [], "", "law", None, [], 0
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^(PREVENTION OF CRUELTY TO ANIMALS )?RULES \(EXPERIMENTS", s) and current and part in ("law", "schedule") and max_law >= 20:
            part, chapter = "rules", ""  # the Rules title page follows the law's Schedule
        m = re.match(r"^CHAPTER [A-Z]+: (.*)$", s)
        if m:
            chapter = m.group(1).title()
            continue
        if re.match(r"^SCHEDULE", s) and part == "law" and max_law >= 20:
            if current:  # close s. 29 before the Schedule's items start
                sections.append((current[0], current[1], current[2], current[3], buf))
            current, buf = None, []
            part, chapter = "schedule", ""
            continue
        if re.match(r"^SCHEDULE", s) and part == "rules":
            if current:  # close the pending section first; the Schedule (application form, omitted) is not a section
                sections.append((current[0], current[1], current[2], current[3], buf))
            current, buf = None, []
            continue
        m = re.match(r"^ {0,8}(\d+)\.\s+(.*)$", line)  # headers may be indented (ss. 21-25 are, in the PDF)
        # a real header continues the numbering of its part; anything else ('1.' inside a list) is body text
        expected = (max_law + 1) if part == "law" else (len([x for x in sections if x[0] == part]) + (1 if current and current[0] == part else 0) + 1)
        if m and int(m.group(1)) in (expected, expected + 1):  # +1: s. 27 is omitted from the translation (a NOTE line)
            num = int(m.group(1))
            if part == "law":
                max_law = num
            if current:
                sections.append((current[0], current[1], current[2], current[3], buf))
            current, buf = (part, m.group(1), chapter, ""), [m.group(2).strip()]
            continue
        if current and s:
            buf.append(s)
    if current:
        sections.append((current[0], current[1], current[2], current[3], buf))
    return sections


def _statute_records():
    recs = []
    for fname, (prefix, lang, title, license_) in STATUTE.items():
        path = LAW_DIR / fname
        if not path.exists():
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        for num, stitle, chapter, buf in sectionize_statute_he(path.read_text(encoding="utf-8")):
            body = " ".join(buf).strip()
            if len(body) < 20:
                continue
            pfx = prefix + ("-schedule" if chapter.startswith("תוספת") else "")  # the Schedule's items restart at 1
            for n, chunk in enumerate(_windows([body]), 1):
                rid = f"{pfx}-s{num}-he" + (f"-{n}" if len(_windows([body])) > 1 else "")
                recs.append({"id": rid, "url": f"etiqtech://resources/law/{fname}#{rid}",
                             "title": f"{title} — {chapter + ' › ' if chapter else ''}סעיף {num}{': ' + stitle if stitle else ''}",
                             "doc_type": "law_section", "jurisdiction": "IL", "lang": "he",
                             "section_path": [x for x in (chapter, f"סעיף {num}") if x], "species": [], "text": chunk,
                             "license": license_, "source": fname, "source_sha256": sha, "retrieved_at": "2026-09-06"})
    en = LAW_DIR / STATUTE_EN
    if en.exists():
        sha = hashlib.sha256(en.read_bytes()).hexdigest()[:12]
        for part, num, chapter, _t, buf in sectionize_statute_en(en.read_text(encoding="utf-8")):
            body = " ".join(buf).strip()
            if len(body) < 20:
                continue
            prefix = {"law": "il-law-1994", "schedule": "il-law-1994-schedule", "rules": "il-rules-2001"}[part]
            doc = ("Prevention of Cruelty to Animals Rules (Experiments on Animals) 5761-2001" if part == "rules"
                   else "Prevention of Cruelty to Animals Law (Experiments on Animals) 5754-1994" + (" — Schedule" if part == "schedule" else ""))
            chunks = _windows([body])
            for n, chunk in enumerate(chunks, 1):
                rid = f"{prefix}-s{num}-en" + (f"-{n}" if len(chunks) > 1 else "")
                recs.append({"id": rid, "url": f"etiqtech://resources/law/{STATUTE_EN}#{rid}",
                             "title": f"{doc} — {chapter + ' › ' if chapter else ''}Section {num}",
                             "doc_type": "law_section", "jurisdiction": "IL", "lang": "en",
                             "section_path": [x for x in (chapter, f"Section {num}") if x], "species": [], "text": chunk,
                             "license": STATUTE_EN_LICENSE, "source": STATUTE_EN, "source_sha256": sha, "retrieved_at": "2026-09-06"})
    return recs


def build():
    en = _records(sectionize_en(EN_SRC.read_text(encoding="utf-8")), "en", DOC_TITLE_EN, EN_SRC.name)
    he = _records(sectionize_he(extract_hebrew()), "he", DOC_TITLE_HE, HE_TXT.name)
    return en + he + _statute_records()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    recs = build()
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    if a.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != payload:
            sys.exit(f"{OUT} is stale — run scripts/build_law_corpus.py")
        print("corpus up to date")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload, encoding="utf-8")
    en, he = [r for r in recs if r["lang"] == "en"], [r for r in recs if r["lang"] == "he"]
    law = [r for r in recs if r["doc_type"] == "law_section"]
    print(f"wrote {OUT.relative_to(ROOT)}: {len(recs)} records ({len(en)} en, {len(he)} he; {len(law)} law/rules sections); "
          f"max chunk {max(len(r['text']) for r in recs)} chars")


if __name__ == "__main__":
    main()
