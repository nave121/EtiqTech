"""P4: a linter-only instance (ETIQTECH_LLM_DISABLED=1) for demos without a GPU."""
import json
from pathlib import Path

from server.app import _analysis_cache, app

HTML = (Path(__file__).resolve().parents[1] / "examples" / "known-good" / "good_IL-010-05-2000.html").read_text(encoding="utf-8")


def test_linter_only_instance(monkeypatch):
    monkeypatch.setenv("ETIQTECH_LLM_DISABLED", "1")
    _analysis_cache.clear()
    app.config["TESTING"] = True
    with app.test_client() as c:
        assert c.get("/api/health").get_json()["llm_enabled"] is False
        prov = c.get("/api/llm-providers").get_json()
        assert prov["llm_enabled"] is False and prov["providers"] == []
        r = c.post("/api/analyze-with-session", json={"html_content": HTML})
        assert r.status_code == 200 and r.get_json()["lint_report"]["checklist"]  # Layer 1 unaffected
        sid = r.get_json()["session_id"]
        for route in (f"/api/llm-verify-stream/{sid}", f"/api/human-eye-stream/{sid}?force=1"):
            body = c.get(route).get_data(as_text=True)
            evt = json.loads(body.split("data: ", 1)[1].strip())
            assert evt["type"] == "error" and evt["code"] == "llm_disabled"
    _analysis_cache.clear()


def test_default_instance_has_llm_enabled(monkeypatch):
    monkeypatch.delenv("ETIQTECH_LLM_DISABLED", raising=False)
    with app.test_client() as c:
        assert c.get("/api/health").get_json()["llm_enabled"] is True
