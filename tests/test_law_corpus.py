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
    assert len(records) >= 80
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)), "ids must be unique and stable"
    for r in records:
        assert REQUIRED <= set(r), r["id"]
        assert r["doc_type"] == "guidance_section" and r["lang"] in ("en", "he")
        assert 40 <= len(r["text"]) <= blc.MAX_CHARS, (r["id"], len(r["text"]))
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
    he = [r for r in records if r["lang"] == "he"]
    assert all(len(r["id"].split("-")[-1]) == 8 or r["id"].split("-")[-2].__len__() == 8 for r in he)
    assert all(len(r["source_sha256"]) == 12 for r in records)
