# Statute sources: the 1994 law and the 2001 rules

`docs/dev-log/statute-sources.md` | research memo, 2026-09-05 | nothing in the repo was changed

## What this answers

Where the Prevention of Cruelty to Animals Law (Experiments on Animals), 5754-1994 and the Prevention of Cruelty to Animals Rules (Experiments on Animals), 5761-2001 are published, in Hebrew and English; how complete and current each copy is; what its licence allows; and what to add to `resources/law/`.

Marker key: **verified** = fetched and read (Hebrew PDFs by text extraction, not by WebFetch summary). **partially verified** = fetched, but a specific detail could not be confirmed from the object. **unverified** = not reachable from here, or a detail taken from a secondary source.

## First, what the repo holds today

`resources/law/README.md` already says it: `the_law-english_translation.txt` (42,599 chars) is the English translation of the Council's explanatory guidance for the permit request form, not the statute. `the_law.txt` is a reversed-word-order extraction of the same PDF, unused. `national-guidance-2025-he.pdf/.txt` is the Hebrew original of that guidance. **The statute and the rules are not in the repo in any language.** This matters for memo 2 as well: the Layer 3 prompt asks the model to cite "Israeli Law Art. 17(b)" style article numbers, and the only "law" block it receives is form guidance. Any article number the model produces today is from memory, not from the prompt.

## Hebrew sources

### Official primary text (Reshumot scans)

| Source | What it is | Status |
|---|---|---|
| https://fs.knesset.gov.il/13/law/13_lsr_211118.pdf | ס"ח 1994, p. 298. The law as passed 19 July 1994. 9 pp., 5 chapters, 29 sections plus תוספת, noisy OCR layer. Original text only, not consolidated. | verified |
| https://fs.knesset.gov.il/13/law/13_lsr_ec_317840.pdf | ת"ט (typo correction): in §2, "הוועדה" becomes "המועצה". The PDF names §2 without a subsection letter; the "p. 365" cite comes from the WikiSource header, not from this PDF. | verified (section), partially verified (page) |
| https://fs.knesset.gov.il/17/law/17_lsr_300644.pdf | ס"ח 2096, 30.5.2007, p. 318. Amendment no. 1: in §10 the words from "אלא על פי" to the end are deleted, so the cosmetics and cleaning-products testing ban becomes absolute. Signed Olmert / Ben-Yizri / Itzik. | verified |
| https://olaw.org.il/laws/law-1808.pdf | ס"ח 1808, 6.9.2001. Claimed to carry a typo fix in §4(1) ("למען" to "למתן") at p. 570. The gazette identity checks out; the index lists corrections at pp. 566 and 569, and the text layer has no "ניסויים", "למתן" or "570". The p. 570 cite rests on the WikiSource header. | partially verified |
| https://olaw.org.il/takanot/takanot-6101.pdf | ק"ת 6101, p. 752. The original 2001 rules. 9 pp., scanned image, no text layer, so contents could not be machine-checked. | partially verified (exists; text not checked) |
| https://olaw.org.il/takanot/takanot-6473.pdf and https://olaw.org.il/takanot/takanot-6474.pdf | ק"ת 2006, pp. 661 and 701. Rules amendment 5766-2006, changes the תוספת (application form). | verified |
| https://olaw.org.il/takanot/takanot-11269.pdf | ק"ת 11269, 30.4.2024, p. 2412. Rules amendment 5784-2024, made under §4(1) of the law. §3(a) now requires submission through the Council's online system on the MoH website, with exactly 11 mandatory items, including (9) absence of alternatives and the search made, and (10) pain, suffering and minimisation methods. §2 cancels the תוספת. In force 31.5.2024. Signed Esther Shohami / Uriel Buso. | verified |
| https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawPrimary.aspx?t=lawlaws&st=lawlaws&lawitemid=2001172 | Knesset national legislation DB entry (lawitemid 2001172). Site returned an empty page to every fetch. ID confirmed only via WikiSource's `{{ח:מאגר|2001172}}` tag. | unverified |

Note on olaw.org.il: it is an unaffiliated mirror of Reshumot PDFs with no about or terms page (`/about` is 404). The gazette text it mirrors is public domain (below); the site's own status is unverified. Cite the gazette, not the site.

Note on WebFetch: its summary of `takanot-11269.pdf` was wrong ("7 items", "committee composition"). Hebrew PDFs were verified by text extraction. Do not trust a fetch summary of a Hebrew PDF.

### Consolidated text, machine-readable

| Source | What it is | Status |
|---|---|---|
| https://he.wikisource.org/wiki/חוק_צער_בעלי_חיים_(ניסויים_בבעלי_חיים) | Full consolidated law, structured markup, per-section anchors, raw via `?action=raw`. Header cites ס"ח תשנ"ד 298, 365; תשס"א 570; תשס"ז 318, matching every Reshumot item above. No amendment after 2007 appears. §27 has no heading here (Nevo titles it "תיקון חוק צער בעלי חיים"). | verified |
| https://he.wikisource.org/wiki/כללי_צער_בעלי_חיים_(ניסויים_בבעלי_חיים) | Consolidated rules, includes the 2024 amendment (§3 marked `תיקון: תשפ״ד`, תוספת marked בוטלה). Header cites ק"ת תשס"א 752; תשס"ו 661, 701; תשפ"ד 2412. | verified |
| https://www.nevo.co.il/law_html/law01/p200m2_003.htm and https://www.nevo.co.il/law_html/law01/p200m2_006.htm | Nevo (commercial) consolidated law and rules, rules current through ק"ת 11269. | verified (content); licence restrictive, see below |

### Nevo-derived mirrors (Nevo's restrictions travel with them)

| Source | What it is | Status |
|---|---|---|
| https://www.weizmann.ac.il/vet/sites/vet/files/uploads/iacuc_law_heb.pdf | Nevo export of the law, footer "נבו הוצאה לאור בע"מ". Includes the 2007 amendment. Current. | verified |
| https://www.weizmann.ac.il/vet/sites/vet/files/uploads/iacuc_regulations.pdf | Nevo export of the rules. **Outdated**: §3(a) still says "לפי הטופס שבתוספת" (pre-2024). Do not use as current text. | verified |
| https://openscholar.huji.ac.il/sites/default/files/mop/files/animal_protection.pdf | Despite the filename, this is the **experiments** law, Nevo "נוסח מלא ומעודכן", PDF title `nevo.co.il`, created 2021-12-28. Live (HTTP 200, 8 pp.). A third Nevo mirror. | verified |

### Regulator (Ministry of Health / Council)

| Source | What it is | Status |
|---|---|---|
| https://www.gov.il/he/departments/units/animal_testing_unit/govil-landing-page | Council landing page. HTTP 403 to every fetch. | unverified |
| https://www.gov.il/he/Departments/DynamicCollectors/animax-meetings | Council meeting index. HTML blocked, but the BlobFolder PDFs behind it fetch. Example, verified: https://www.gov.il/BlobFolder/dynamiccollectorresultitem/p26102025/he/files_databases_animax_meetings_p26102025.pdf, 58-page protocol of the 26.10.2025 meeting chaired by Prof. Esti Shohami, with member roster. | partially verified |
| https://www.gov.il/he/departments/general/animax-applications | The online application system §3(a) now points to. URL from search index only. | unverified |
| https://www.health.gov.il/LegislationLibrary/Veter06.pdf | MoH copy of the 2001 rules. Returns HTTP 202 with 0 bytes (bot wall). | unverified |

The Council's own נהלים could not be enumerated because the index pages 403. Guidance PDFs are reachable once you have a blob URL.

## English sources

**Finding: there is no official English translation, and there cannot be one for this statute.** Israeli law is enacted and published in Hebrew. The Ministry of Justice's authorised series, Laws of the State of Israel, ran vols. 1 to 45 and stopped at 1989/90, four years before this law (https://www.nyulawglobal.org/globalex/israel1.html, verified). Every English text found is private, and all of them are one translation.

| Source | What it is | Status |
|---|---|---|
| https://www.weizmann.ac.il/vet/sites/vet/files/uploads/iacuc_law_en.pdf | Law (ss. 1 to 29 + Schedule) and Rules (ss. 1 to 11), "correct as of May 30, 2007", 14 pp., 118 KB. Two translator-declared gaps, both printed in the text: s. 27 ("here its translation is consequently omitted") and the Rules' Schedule ("(omitted)"). No translator credit, no copyright notice. PDF author metadata "Hagit Dafni" (Weizmann vet services). Same translation as the AAALAC file (text identical after whitespace normalisation, SequenceMatcher ratio 0.988), with two deltas: "head researcher" became "principal investigator", and a footnote that the Minister of Religious Affairs' power passed to the Minister of Health (YP 5266, 21.1.2004, p. 1643). | verified |
| https://www.aaalac.org/pub/DCF12A06-C1B3-1978-F28F-79C2C0914FF3 | Same Law + Rules, "correct as of December 1, 2005", 15 pp. Linked as Israel's entry on https://www.aaalac.org/resources/regulations-resources/. PDF metadata author `אריה גרינפלד` (Aryeh Greenfield), created 16 Sep 2006. Greenfield / A.G. Publications, Haifa is the standard private publisher of Israeli statutes in English (GlobaLex, verified). **Attribution rests on file metadata, not a printed credit.** | verified (content); attribution partially verified |
| https://research.technion.ac.il/wp-content/uploads/2014/11/EXPERIMENTS-ON-ANIMALS_Israel-Law.pdf | Same 2005 text, different file (52,953 bytes vs AAALAC's 62,536; different mod dates). Same `/Author` metadata. Server rejects non-browser user agents. | verified |
| `http://animals.huji.ac.il/upload/105PREVENTION-OF-CRUELTY-TO-ANIMALS-LAW-(EXPERIMENTS-ON-ANIMALS)-5754-1994.pdf` | Appears in search results; returns a 580-byte HTML error stub. Dead. | verified dead |
| http://www.chai.org.il/en/compassion/legislation_experimentation.htm | Host resolves, page returns HTTP 404. Whether it was a translation or a summary is unknown. | unverified |

Licence of the Greenfield translation: **not open.** A.G. Publications translations are sold commercially; no CC or reuse permission was found anywhere. Whether AAALAC, Weizmann and Technion host it with permission is unverified. Cite and link; do not copy the text into the repo.

### Wrong law, commonly mistaken for it

- https://www.animallaw.info/sites/default/files/stisreal_animal_protection.pdf is the Cruelty to Animals Law (Animal Protection) 5754-1994, a different statute. Its own s. 22(2) excludes experiments "carried out under the Cruelty to Animals Law (Animal Experiments), 5754-1994". The Michigan State index at https://www.animallaw.info/countries/israel lists only the protection law, the geese force-feeding regulations and the 2015 pig regulations. No experiments-law translation there. Verified.
- ECOLEX (https://www.ecolex.org/details/legislation/animal-cruelty-animal-protection-law-5754-1994-lex-faoc219163/) and UNEP LEAP (https://leap.unep.org/en/countries/il/national-legislation/animal-cruelty-animal-protection-law-5754-1994) both hold the protection law, with operative text and a FAOLEX PDF link. No experiments-law record surfaced. Verified for the protection law; absence of an experiments-law record is unverified (absence of evidence).

### Checked and empty

- https://norecopa.no/legislation/ : read once, no crawling. No Israel mention. Verified.
- gov.il / MoH: no English text of the law, rules or Council pages found. Unverified (403s).
- Academic secondary sources (paraphrase, not translations, all paywalled, unverified): https://www.sciencedirect.com/science/article/pii/B9780123978561000064, https://pubmed.ncbi.nlm.nih.gov/12017891/, https://pubmed.ncbi.nlm.nih.gov/24660572/.

## Licence summary

- **Statute and rules text (Hebrew): public domain.** Copyright Act 5768-2007, §6: "על אף הוראות סעיף 4, לא תהא זכות יוצרים בחוקים, בתקנות, בדברי הכנסת ובהחלטות שיפוטיות..." Verified at https://he.wikisource.org/wiki/חוק_זכות_יוצרים. This covers the text, not any publisher's typesetting, annotations or consolidation work.
- **WikiSource pages: CC BY-SA 4.0** under the Wikimedia Terms of Use for the markup and editorial layer; the underlying legal text is PD. Only source here whose reuse terms are unambiguously permissive. Verified.
- **Nevo: reference only, never ingest.** Terms at https://www.nevo.co.il/general/TermsOfUse.aspx, verified verbatim: use limited to "מטרות אקדמיות ומתן שירותי יעוץ משפטיים"; forbidden to build legal databases or commercial information services; crawlers and scraping forbidden; AI use forbidden "לצורך עיבוד, ניתוח, כרייה, סיכום, אימון, כוונון (fine-tuning)". Clause numbers (§2.7, §3, §4 in the earlier draft) are unverified; the rendered page shows no numbering I could tie to them. The Weizmann and HUJI Hebrew PDFs carry Nevo's imprint, so the same bar applies to them.
- **Greenfield English translation: all rights reserved by default.** No licence stated, commercial publisher. Link only.
- **Knesset and gov.il terms of use: unverified** (pages blocked). Do not state a reuse licence for Knesset or gov.il hosted documents. The gazette text itself is PD under §6 regardless of host.

## Recommendation for `resources/law/`

1. **Add the Hebrew consolidated law and rules from WikiSource**, fetched via `?action=raw`, as `law-he-5754-1994.txt` and `rules-he-5761-2001.txt` (or similar; keep the existing guidance files as they are and fix nothing about their names in this step). Attribution line at the top of each file and in the README:

   > Text: חוק צער בעלי חיים (ניסויים בבעלי חיים), התשנ"ד-1994, consolidated. Public domain under Israeli Copyright Act 5768-2007 §6. Consolidation and markup from Hebrew WikiSource, CC BY-SA 4.0, https://he.wikisource.org/wiki/חוק_צער_בעלי_חיים_(ניסויים_בבעלי_חיים), retrieved 2026-09-05. Primary sources: ס"ח תשנ"ד 298, 365; תשס"א 570; תשס"ז 318. Current through ס"ח 2096 (30.5.2007).

   Same shape for the rules with ק"ת תשס"א 752; תשס"ו 661, 701; תשפ"ד 2412, current through ק"ת 11269 (in force 31.5.2024). Keep the WikiSource "not legal advice" disclaimer.
2. **Add a `SOURCES.md` (or extend the README) listing the Reshumot PDFs above** as the primary citations, with the verified/partially verified markers carried over. The Knesset fs.knesset.gov.il links are the official scans; the olaw.org.il links are mirrors and should be labelled as such.
3. **English: link, do not copy.** Add to the README: "Unofficial English translation (Law + Rules, current to 30 May 2007, s. 27 and the Rules' Schedule omitted by the translator): https://www.weizmann.ac.il/vet/sites/vet/files/uploads/iacuc_law_en.pdf ; 2005 edition hosted by AAALAC at https://www.aaalac.org/pub/DCF12A06-C1B3-1978-F28F-79C2C0914FF3 . Translator identified from PDF metadata as Aryeh Greenfield (A.G. Publications); no licence stated." If the maintainer wants English statute text inside prompts, the options are (a) a fresh translation done for the project and licensed by the project, or (b) short quotations with citation. Neither exists yet; this memo does not decide it.
4. **Fix the misleading filename or the prompt, not both later.** `the_law-english_translation.txt` is form guidance. Either rename it (`council-guidance-en.txt`) and update `_load_full_law_text` and `scripts/build_law_corpus.py`, or leave the name and make the prompt stop calling it the law. Memo 2 assumes the statute will be added and retrieved by section, so the rename is the cleaner path. Maintainer's call; renaming touches the corpus builder and CI's stale-corpus check.
5. **Do not add** anything from Nevo, the Weizmann Hebrew PDFs, or the HUJI PDF. Do not add the Greenfield text.

## What must not be assumed

- That an official English translation exists. It does not; the authorised series ended in 1989/90.
- That the English translation in circulation is current. It is dated 30 May 2007 and covers the 2007 law amendment but not the 2024 rules amendment (§3(a) and the cancelled Schedule).
- That "no amendment after 2007" is confirmed by the official database. It rests on WikiSource and Nevo agreeing; main.knesset.gov.il was unreachable.
- That the 2001 rules were made under §4(1),(2),(4). The 2001 gazette has no text layer; the 2024 amendment recites §4(1) only.
- That the law uses the term "3Rs". It does not. Replacement is §9; Refinement is in תוספת items 1 and 3 and rules §5; species choice is תוספת item 2. Reduction is not stated as such.
- That gov.il or Knesset hosted documents carry a reuse licence. Unverified.
- That a WebFetch summary of a Hebrew PDF is accurate. It was not, once, in this work.
