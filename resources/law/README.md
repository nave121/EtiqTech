# Law and guidance corpus (runtime assets)

These files are loaded at runtime to ground the LLM layers. They are **not**
examples — a deployment without them runs "law-grounded" review with no law
text, which is why `/api/health` reports `law_loaded` and the server warns at
startup when they are missing.

| File | What |
|------|------|
| `statute-1994-he.txt` | **The statute**: חוק צער בעלי חיים (ניסויים בבעלי חיים), התשנ״ד–1994, consolidated (incl. the 2007 amendment), imported from Hebrew WikiSource by `scripts/import_statute.py`. The statute text carries no copyright (Israeli Copyright Act 2007, s. 6); WikiSource's markup layer is CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/); changes made: templates and category links stripped, sections re-flowed as plain text. Source: https://he.wikisource.org/wiki/חוק_צער_בעלי_חיים_(ניסויים_בבעלי_חיים) |
| `rules-2001-he.txt` | **The rules**: כללי צער בעלי חיים (ניסויים בבעלי חיים), התשס״א–2001, consolidated incl. the 2024 amendment (online submission, 11 mandatory items). Same provenance and terms. Source: https://he.wikisource.org/wiki/כללי_צער_בעלי_חיים_(ניסויים_בבעלי_חיים) |
| `statute-and-rules-2007-en.txt` | Private **English translation** of both, "correct as of May 30, 2007" (predates the 2024 rules amendment), from the Weizmann Institute veterinary resources page (https://www.weizmann.ac.il/vet/sites/vet/files/uploads/iacuc_law_en.pdf). Licence not stated: **redistribution terms unverified**; used as grounding text. This is now `LAW_PATH` (the "law excerpt" the LLM prompts quote). |
| `the_law-english_translation.txt` | English translation of the Council's explanatory guidance for the request form (same document as the 2025 PDF). Despite the filename it is **not** the 1994 statute text. Served through the retrieval corpus (`guidance_section`). |
| `the_law.txt` | Older text extraction of the same PDF with word order reversed per line (visual-order artifact). Not used by any code; kept until the maintainer removes it. |
| `national-guidance-2025-he.pdf` | National Council general guidance for filling the request form, 2025 update (Hebrew original) |
| `national-guidance-2025-he.txt` | Clean `pdftotext` extraction of the PDF (logical order). Source for the Hebrew half of `resources/corpus/guidance_il.jsonl`. |

Note on naming: `the_law-english_translation.txt` is the English translation of the
Council's *explanatory guidance for the request form*, not the text of the Prevention of
Cruelty to Animals Law (Experiments on Animals), 5754-1994 itself. The statute is not in
the repo until 2026-09-06 (see `docs/dev-log/statute-sources.md` for the full source survey).

The retrieval corpus is built deterministically from these files by
`scripts/build_law_corpus.py` and committed at `resources/corpus/guidance_il.jsonl`
(CI checks it is not stale).
