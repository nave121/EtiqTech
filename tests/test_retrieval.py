"""Phase 2 retrieval: local index with metadata filters, lexical fallback, graceful degrade,
and the prompt/result integration (grounding refs with source URLs)."""
import hashlib
import json
import math

import pytest

import src.llm_agent as llm_agent
import src.retrieval as retrieval
from src.contracts import VerifierResult
from src.llm_clients import LLMError
from src.retrieval import Retriever, format_grounding_block, grounding_refs


def _fake_embed(texts, model=None):
    """Deterministic bag-of-words hashing embedder: shared words -> higher cosine."""
    vecs = []
    for t in texts:
        v = [0.0] * 64
        for tok in retrieval._tokens(t):
            v[int(hashlib.md5(tok.encode(), usedforsecurity=False).hexdigest(), 16) % 64] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        vecs.append([x / n for x in v])
    return vecs


RECORDS = [
    {"id": "a", "title": "Alternatives search", "doc_type": "guidance_section", "species": [],
     "text": "how to search for alternatives replacement reduction refinement databases", "url": "etiqtech://a", "license": "L"},
    {"id": "b", "title": "Euthanasia", "doc_type": "guidance_section", "species": [],
     "text": "euthanasia method humane endpoints fate of the animal", "url": "etiqtech://b", "license": "L"},
    {"id": "c", "title": "Mouse refinement", "doc_type": "norina_record", "species": ["mouse"],
     "text": "refinement of mouse handling tunnel handling alternatives", "url": "https://norecopa.no/x", "license": "CC BY 4.0"},
    {"id": "d", "title": "Zebrafish refinement", "doc_type": "norina_record", "species": ["zebrafish"],
     "text": "refinement alternatives for zebrafish anaesthesia", "url": "https://norecopa.no/y", "license": "CC BY 4.0"},
]


@pytest.fixture
def retriever(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval, "embed_texts", _fake_embed)
    return Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path)


def test_embedding_search_ranks_by_similarity_and_filters(retriever):
    hits = retriever.search("search for alternatives databases replacement", k=2)
    assert hits[0].id == "a" and hits[0].method == "embedding"
    only_guidance = retriever.search("refinement alternatives", k=4, doc_types=["guidance_section"])
    assert {h.id for h in only_guidance} <= {"a", "b"}
    mouse = retriever.search("refinement alternatives", k=4, doc_types=["norina_record"], species=["mouse"])
    assert [h.id for h in mouse] == ["c"]  # zebrafish record filtered out; species-agnostic would pass


def test_species_agnostic_records_match_any_species(retriever):
    hits = retriever.search("euthanasia endpoints", k=4, species=["rat"])
    assert "b" in {h.id for h in hits}


def test_index_is_cached_on_disk_and_reused(retriever, tmp_path, monkeypatch):
    assert retriever.build_index() is True
    cache = list(tmp_path.glob("fake-*.json"))
    assert len(cache) == 1 and len(json.loads(cache[0].read_text())) == len(RECORDS)
    calls = []
    monkeypatch.setattr(retrieval, "embed_texts", lambda texts, model=None: calls.append(len(texts)) or _fake_embed(texts))
    fresh = Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path)
    fresh.search("euthanasia", k=1)
    assert calls == [1], "corpus vectors must come from the cache; only the query is embedded"


def test_lexical_fallback_when_embeddings_unavailable(monkeypatch, tmp_path):
    def boom(texts, model=None):
        raise LLMError("no embed endpoint")
    monkeypatch.setattr(retrieval, "embed_texts", boom)
    r = Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path)
    hits = r.search("euthanasia humane endpoints", k=2)
    assert hits and hits[0].id == "b" and hits[0].method == "lexical"
    assert "unavailable" in r.last_error
    r.search("חיפוש", k=1)  # Hebrew tokens go through \w; must not raise


def test_lexical_fallback_does_not_hammer_a_dead_endpoint(monkeypatch, tmp_path):
    calls = []
    def boom(texts, model=None):
        calls.append(1)
        raise LLMError("down")
    monkeypatch.setattr(retrieval, "embed_texts", boom)
    r = Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path)
    for _ in range(5):
        r.search("euthanasia", k=1)
    assert len(calls) == 1  # one failed index build, then cooldown


def test_search_never_raises_on_empty_or_unmatched(retriever):
    assert retriever.search("", k=3) == []
    assert retriever.search("anything", k=3, doc_types=["law_section"]) == []


def test_grounding_block_and_refs_carry_source_urls(retriever):
    hits = retriever.search("euthanasia", k=2)
    block = format_grounding_block(hits)
    assert block.startswith("Grounding references") and "[G1]" in block and "Source: etiqtech://" in block
    refs = grounding_refs(hits)
    assert refs[0]["ref"] == "G1" and refs[0]["url"] and refs[0]["license"] == "L"


# ---- integration with the theme prompts --------------------------------------

@pytest.fixture
def grounded_agent(monkeypatch, retriever):
    monkeypatch.setenv("ETIQTECH_GROUNDING", "1")
    monkeypatch.setattr(retrieval, "_default", retriever)
    return retriever


def test_grounding_off_by_default_never_touches_retrieval(monkeypatch):
    monkeypatch.delenv("ETIQTECH_GROUNDING", raising=False)
    monkeypatch.setattr(llm_agent, "_retrieve_grounding", lambda *a, **k: pytest.fail("retrieval must not run when disabled"))
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda *a, **k: iter(["{}"]))
    events = list(llm_agent.run_verification_stream({"animals_total": []}, {"checklist": []}))
    assert events[-1]["result"]["grounding_notice"] is None
    assert all(t["grounding"] == [] for t in events[-1]["result"]["themes"].values())


def test_grounded_prompt_cites_sources_and_results_carry_refs(grounded_agent, monkeypatch):
    prompts = []
    def fake_stream(prompt, **_):
        prompts.append(prompt)
        return iter([json.dumps({"three_Rs_alternatives": {"score": 3, "rationale": "Alternatives searched [G1]"}, "questions": []})])
    monkeypatch.setattr(llm_agent, "call_llm_stream", fake_stream)
    instance = {"animals_total": [{"species_standard": "mouse"}]}
    events = list(llm_agent.run_verification_stream(instance, {"checklist": []}))
    final = events[-1]["result"]
    VerifierResult(**final)  # grounding refs are part of the public contract
    refs = final["themes"]["three_Rs_alternatives"]["grounding"]
    assert refs and refs[0]["ref"] == "G1" and refs[0]["url"]
    assert any("cite it in the rationale as [G1]" in p and "Law and guidance grounding:" in p for p in prompts)
    assert not any("Law excerpt (trimmed)" in p for p in prompts), "the fixed law prefix is replaced when grounded"
    assert final["grounding_notice"] is None
    assert not [e for e in events if e["type"] == "warning"]


def test_grounding_degrades_with_visible_notice(monkeypatch, tmp_path):
    monkeypatch.setenv("ETIQTECH_GROUNDING", "1")
    def boom(texts, model=None):
        raise LLMError("down")
    monkeypatch.setattr(retrieval, "embed_texts", boom)
    monkeypatch.setattr(retrieval, "_default", Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path))
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda *a, **k: iter(["{}"]))
    events = list(llm_agent.run_verification_stream({"animals_total": []}, {"checklist": []}))
    warnings = [e for e in events if e["type"] == "warning" and e["code"] == "grounding"]
    assert len(warnings) == 1 and "degraded" in warnings[0]["message"]
    assert events[-1]["type"] == "complete" and "degraded" in events[-1]["result"]["grounding_notice"]


def test_retrieval_failure_falls_back_to_ungrounded_review(monkeypatch):
    monkeypatch.setenv("ETIQTECH_GROUNDING", "1")
    class Broken:
        def search(self, *a, **k):
            raise RuntimeError("index exploded")
    monkeypatch.setattr(retrieval, "_default", Broken())
    prompts = []
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda p, **_: prompts.append(p) or iter(["{}"]))
    events = list(llm_agent.run_verification_stream({"animals_total": []}, {"checklist": []}))
    assert events[-1]["type"] == "complete"
    assert "unavailable" in events[-1]["result"]["grounding_notice"]
    assert all("Law excerpt (trimmed)" in p for p in prompts)  # today's behaviour, not a hard failure


def test_cache_key_changes_when_a_title_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval, "embed_texts", _fake_embed)
    a = Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path)
    edited = [dict(RECORDS[0], title="Alternatives search (revised)")] + RECORDS[1:]
    b = Retriever(edited, embed_model="fake", cache_dir=tmp_path)
    assert a._cache_path() != b._cache_path()


def test_cache_write_is_atomic_and_partial_files_are_rebuilt(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval, "embed_texts", _fake_embed)
    r = Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path)
    r.build_index()
    (path,) = tmp_path.glob("fake-*.json")
    assert not list(tmp_path.glob("*.tmp"))
    path.write_text('[[0.1, 0.2')  # simulate a torn write from another process
    fresh = Retriever(RECORDS, embed_model="fake", cache_dir=tmp_path)
    assert fresh.build_index() is True and len(fresh._vectors) == len(RECORDS)


def test_species_helper_tolerates_malformed_shapes():
    from src.llm_agent import _instance_species
    assert _instance_species({"animals_total": {"species_standard": "mouse"}}) == []
    assert _instance_species({"animals_total": ["x", None, {"species_standard": "rat"}]}) == ["rat"]
