"""P0.2: the law corpus is a runtime asset — its absence must be loud, never silent."""
import logging
from pathlib import Path

import src.llm_agent as llm_agent
from server.app import app


def test_law_corpus_ships_in_resources():
    assert llm_agent.LAW_PATH == Path(llm_agent.__file__).resolve().parent.parent / "resources" / "law" / "the_law-english_translation.txt"
    assert llm_agent.law_loaded()
    assert llm_agent._load_law_text(max_chars=50)


def test_health_reports_law_loaded():
    with app.test_client() as client:
        body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["law_loaded"] is True


def test_missing_law_warns_and_health_goes_false(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(llm_agent, "LAW_PATH", tmp_path / "nope.txt")
    monkeypatch.setattr(llm_agent, "_law_missing_warned", False)
    assert llm_agent.law_loaded() is False
    with caplog.at_level(logging.WARNING, logger="src.llm_agent"):
        assert llm_agent._load_law_text() == ""
        assert llm_agent._load_law_text() == ""  # second call: still empty, warns once
    assert sum("Law text missing" in r.message for r in caplog.records) == 1
    with app.test_client() as client:
        assert client.get("/api/health").get_json()["law_loaded"] is False
