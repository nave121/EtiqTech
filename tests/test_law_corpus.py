"""Phase 2 (unblocked half): the guidance corpus is deterministic, well-formed, and committed."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_law_corpus as blc  # noqa: E402

REQUIRED = {"id", "url", "title", "doc_type", "species", "text", "license", "retrieved_at", "lang", "section_path", "source"}


@pytest.fixture(scope="module")
def records():
    return [json.loads(l) for l in blc.OUT.read_text(encoding="utf-8").splitlines()]


def test_committed_corpus_matches_the_builder():
    assert blc.OUT.exists()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_law_corpus.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_schema_and_uniqueness(records):
    assert len(records) >= 160
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)), "ids must be unique and stable"
    for r in records:
        assert REQUIRED <= set(r), r["id"]
        assert r["doc_type"] in ("guidance_section", "law_section") and r["lang"] in ("en", "he")
        floor = 20 if r["doc_type"] == "law_section" else 40  # a statute section can be one sentence (s. 26 is 36 chars)
        assert floor <= len(r["text"]) <= blc.MAX_CHARS, (r["id"], len(r["text"]))
        assert r["url"].startswith("etiqtech://resources/law/")


def test_hebrew_is_in_logical_order_not_word_reversed(records):
    he = " ".join(r["text"] for r in records if r["lang"] == "he")
    assert "בשנת 1994 חוקקה כנסת ישראל" in he  # the_law.txt (reversed extraction) has 'ישראל כנסת חוקקה 1994 בשנת'
    assert "עמוד –" not in " ".join(r["section_path"][0] for r in records if r["lang"] == "he")


def test_english_wrapped_headings_are_merged(records):
    titles = " | ".join(r["title"] for r in records if r["lang"] == "en")
    assert "Participants and Training" in titles
    assert "Purpose of Animal Use in Research" in titles


def test_key_topics_are_retrievable_units(records):
    en_ids = [r["id"] for r in records if r["lang"] == "en"]
    for needle in ("search-for-alternatives", "severity-level-classification", "euthanasia", "reasoning-for-number-of-animals", "analgesia"):
        assert any(needle in i for i in en_ids), needle


def test_subheadings_are_not_swallowed_by_part_headings(records):
    paths = [tuple(r["section_path"]) for r in records if r["lang"] == "en"]
    assert any(p[0].startswith("Part C") and p[-1] == "The Principal Investigator" and len(p) == 2 for p in paths)
    assert not any("part-c-in-the-request-form-the-principal" in r["id"] for r in records)


def test_urls_and_latin_spans_survive_hebrew_normalization(records):
    he = " ".join(r["text"] for r in records if r["lang"] == "he")
    assert "https://eurl-ecvam.jrc.ec.europa.eu" in he
    assert "https: //" not in he and "()EURL" not in he and "(EURL ECVAM)" in he


def test_hebrew_ids_are_content_hashes_with_provenance(records):
    he = [r for r in records if r["lang"] == "he" and r["doc_type"] == "guidance_section"]
    assert all(len(r["id"].split("-")[-1]) == 8 or r["id"].split("-")[-2].__len__() == 8 for r in he)
    assert all(len(r["source_sha256"]) == 12 for r in records)


def test_statute_and_rules_are_in_the_corpus(records):
    law = [r for r in records if r["doc_type"] == "law_section"]
    ids = {r["id"] for r in law}
    assert "il-law-1994-s1-he" in ids and "il-law-1994-s1-en-1" in ids or "il-law-1994-s1-en" in ids
    assert any(i.startswith("il-rules-2001-s") and i.endswith("-he") for i in ids)
    assert any(i.startswith("il-rules-2001-s") and "-en" in i for i in ids)
    assert all(r["jurisdiction"] == "IL" and r["license"] for r in law)
    he1 = next(r for r in law if r["id"] == "il-law-1994-s1-he")
    assert "הגדרות" in he1["title"] and "בעל חוליות למעט אדם" in he1["text"]


def test_english_statute_sections_do_not_bleed_into_neighbours(records):
    """The PDF prints each section's title above its number; that line must become the NEXT section's title,
    never the previous section's last words (found by review: 39 of 40 English records were affected)."""
    en = [r for r in records if r["doc_type"] == "law_section" and r["lang"] == "en"]
    titles = [r["title"].split(": ", 1)[1] for r in en if ": " in r["title"].split(" — ")[-1]]
    assert len(titles) >= 30, "English sections should carry their parsed titles"
    for r in en:
        tail = r["text"].rstrip()[-80:]
        for t in titles:
            if len(t) > 8:
                assert not tail.endswith(t), (r["id"], tail)
        assert not tail.endswith("PREVENTION OF CRUELTY TO ANIMALS"), r["id"]
    s21 = next(r for r in en if r["id"] == "il-law-1994-s21-en")
    assert "Supervisor of experiments in the defense establishment" in s21["title"]
    assert s21["text"].startswith("(a)")
