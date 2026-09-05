"""P3.5: feedback store is an allowlist of metadata — nothing else can get in."""
import json
import sqlite3

import pytest

from src import feedback
from server.app import app


@pytest.fixture
def db(monkeypatch, tmp_path):
    path = tmp_path / "fb.sqlite"
    monkeypatch.setenv("FEEDBACK_DB", str(path))
    monkeypatch.delenv("ETIQTECH_FEEDBACK", raising=False)
    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    app.config["RATELIMIT_ENABLED"] = False
    yield path
    app.config["RATELIMIT_ENABLED"] = True


def _post(client, body):
    return client.post("/api/feedback", data=json.dumps(body), content_type="application/json")


def test_valid_feedback_is_recorded_and_reported(db):
    with app.test_client() as c:
        assert _post(c, {"kind": "lint", "key": "euthanasia:CO2", "verdict": "down", "ruleset_version": "1.0.0", "profile": "default"}).status_code == 200
        assert _post(c, {"kind": "lint", "key": "euthanasia:CO2", "verdict": "up"}).status_code == 200
        assert _post(c, {"kind": "llm", "key": "three_Rs_alternatives", "verdict": "down"}).status_code == 200
        rows = c.get("/api/feedback/report").get_json()["rows"]
    by = {(r["kind"], r["key"]): r for r in rows}
    assert by[("lint", "euthanasia:CO2")]["down"] == 1 and by[("lint", "euthanasia:CO2")]["up"] == 1
    assert by[("llm", "three_Rs_alternatives")]["down_rate"] == 1.0
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(feedback)")]
    assert cols == ["id", "created_at", "kind", "key", "verdict", "ruleset_version", "profile"]


@pytest.mark.parametrize("body", [
    {"kind": "lint", "key": "euthanasia:CO2", "verdict": "down", "comment": "the protocol says..."},  # free text
    {"kind": "lint", "key": "euthanasia:CO2", "verdict": "down", "session_id": "abc"},
    {"kind": "lint", "key": "not:a:rule", "verdict": "down"},
    {"kind": "llm", "key": "euthanasia:CO2", "verdict": "down"},  # rule id under the wrong kind
    {"kind": "lint", "key": "euthanasia:CO2", "verdict": "meh"},
    {"kind": "lint", "key": "euthanasia:CO2", "verdict": "down", "profile": "x" * 40},
    {"kind": "lint", "key": "euthanasia:CO2", "verdict": "down", "profile": "SPECIES:Macaca;N=12"},  # text in an 'enum'
    {"kind": "lint", "key": "euthanasia:CO2", "verdict": "down", "ruleset_version": "see protocol p.3"},
    "not json",
    None,
])
def test_anything_beyond_the_allowlist_is_rejected(db, body):
    with app.test_client() as c:
        r = c.post("/api/feedback", data=json.dumps(body) if body is not None else "", content_type="application/json")
    assert r.status_code == 400
    assert not db.exists() or sqlite3.connect(db).execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0


def test_feedback_can_be_disabled(db, monkeypatch):
    monkeypatch.setenv("ETIQTECH_FEEDBACK", "0")
    with app.test_client() as c:
        assert _post(c, {"kind": "lint", "key": "euthanasia:CO2", "verdict": "up"}).status_code == 404
        assert c.get("/api/feedback/report").status_code == 404
    assert not db.exists()


def test_store_write_failure_is_a_503_not_a_crash(db, monkeypatch):
    monkeypatch.setattr(feedback, "record", lambda row: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with app.test_client() as c:
        assert _post(c, {"kind": "lint", "key": "euthanasia:CO2", "verdict": "up"}).status_code == 503
