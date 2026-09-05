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
