# Law and guidance corpus (runtime assets)

These files are loaded at runtime to ground the LLM layers. They are **not**
examples — a deployment without them runs "law-grounded" review with no law
text, which is why `/api/health` reports `law_loaded` and the server warns at
startup when they are missing.

| File | What |
|------|------|
| `the_law-english_translation.txt` | English translation of the Council's explanatory guidance for the request form (same document as the 2025 PDF). Despite the filename it is **not** the 1994 statute text. Used in prompts. |
| `the_law.txt` | Older text extraction of the same PDF with word order reversed per line (visual-order artifact). Not used by any code; kept until the maintainer removes it. |
| `national-guidance-2025-he.pdf` | National Council general guidance for filling the request form, 2025 update (Hebrew original) |
| `national-guidance-2025-he.txt` | Clean `pdftotext` extraction of the PDF (logical order). Source for the Hebrew half of `resources/corpus/guidance_il.jsonl`. |

Note on naming: `the_law-english_translation.txt` is the English translation of the
Council's *explanatory guidance for the request form*, not the text of the Prevention of
Cruelty to Animals Law (Experiments on Animals), 5754-1994 itself. The statute is not in
the repo; adding it (Hebrew + a vetted translation) is on the maintainer.

The retrieval corpus is built deterministically from these files by
`scripts/build_law_corpus.py` and committed at `resources/corpus/guidance_il.jsonl`
(CI checks it is not stale).
