"""P3.3: the canonical schema is the public contract; adapters are the way in."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.adapters import ADAPTERS, IngestError, ingest, item_skeleton, parse_canonical_json, schema_errors, schema_skeleton
from src.linter_renderer import lint
from server.app import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "adapters"))
import minimal_adapter  # noqa: E402

GOOD_HTML = (ROOT / "examples" / "known-good" / "good_IL-010-05-2000.html").read_text(encoding="utf-8")


def test_skeleton_validates_and_lints():
    inst = schema_skeleton()
    assert schema_errors(inst) == []
    assert lint(inst)["status"] in ("pass", "fail")  # runs, no crash
    exp = item_skeleton("experiments")
    assert "animals" in exp and "euthanasia" in exp
    with pytest.raises(KeyError):
        item_skeleton("header")


def test_example_adapter_produces_a_valid_reviewable_instance():
    inst = minimal_adapter.to_canonical(minimal_adapter.EXAMPLE)
    assert schema_errors(inst) == []
    report = lint(inst, profile="default")
    assert report["ruleset_version"] and report["checklist"]
    r = subprocess.run([sys.executable, str(ROOT / "examples" / "adapters" / "minimal_adapter.py")], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["header"]["protocol_id"] == "90042"


def test_ingest_dispatches_by_extension_and_by_detection():
    inst, name = ingest(GOOD_HTML, "x.html")
    assert name == "il-council-html" and inst["header"]["protocol_id"]
    inst2, name2 = ingest(GOOD_HTML.encode("utf-8"))  # no filename -> detection
    assert name2 == "il-council-html" and inst2 == inst
    canon = json.dumps(schema_skeleton())
    assert ingest(canon, "p.json")[1] == "canonical-json"
    assert ingest(canon)[1] == "canonical-json"
    with pytest.raises(IngestError, match="Invalid file type"):
        ingest(canon, "p.pdf")
    with pytest.raises(IngestError, match="Unrecognized"):
        ingest("just some text")
    with pytest.raises(IngestError, match="UTF-8"):
        ingest(b"\xff\xfe\x00bad", "x.html")


def test_canonical_json_errors_name_paths_not_values():
    inst = schema_skeleton()
    inst["experiments"] = [dict(item_skeleton("experiments"), severity_level_1_to_5="SECRET-VALUE-7")]
    inst["research"]["request_type"] = "SECRET-ENUM"
    with pytest.raises(IngestError) as ei:
        parse_canonical_json(json.dumps(inst))
    msg = str(ei.value)
    assert "experiments/0/severity_level_1_to_5" in msg and "research/request_type" in msg
    assert "SECRET" not in msg
    with pytest.raises(IngestError, match="Invalid JSON"):
        parse_canonical_json("{not json")
    with pytest.raises(IngestError, match="object"):
        parse_canonical_json("[1,2]")


def test_api_accepts_canonical_json_and_reports_adapter():
    inst = minimal_adapter.to_canonical(minimal_adapter.EXAMPLE)
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/analyze", json={"instance": inst})
        assert r.status_code == 200 and r.get_json()["adapter"] == "canonical-json"
        r = c.post("/api/analyze", json={"html_content": GOOD_HTML})
        assert r.status_code == 200 and r.get_json()["adapter"] == "il-council-html"
        bad = dict(inst); bad["header"] = {}
        r = c.post("/api/analyze-with-session", json={"instance": bad})
        assert r.status_code == 400 and "header" in r.get_json()["error"]
        from io import BytesIO
        r = c.post("/api/analyze", data={"file": (BytesIO(json.dumps(inst).encode()), "p.json")}, content_type="multipart/form-data")
        assert r.status_code == 200 and r.get_json()["adapter"] == "canonical-json"


def test_schema_doc_is_generated_and_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_schema_doc.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_registry_extensions_drive_allowed_uploads():
    from server.app import ALLOWED_EXTENSIONS
    assert ALLOWED_EXTENSIONS == {e for a in ADAPTERS.values() for e in a.extensions} == {"html", "htm", "json"}


def test_schema_error_messages_never_embed_values_for_any_validator():
    """Future-proof: run a synthetic schema through the keywords jsonschema would echo values for."""
    import jsonschema
    from src import adapters
    marker = "SECRET-VALUE-9f8e"
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "a": {"type": "array", "minItems": 3, "uniqueItems": True},
        "b": {"anyOf": [{"type": "integer"}, {"const": "x"}]},
        "c": {"type": "string", "pattern": "^ok$", "maxLength": 3},
    }}
    v = jsonschema.validators.validator_for(schema)(schema)
    inst = {"a": [marker, marker], "b": marker, "c": marker, marker: 1}
    orig = adapters._validator
    adapters._validator = v
    try:
        msgs = adapters.schema_errors(inst, limit=50)
    finally:
        adapters._validator = orig
    assert msgs and all(marker not in m for m in msgs), msgs


def test_deeply_nested_json_is_a_400_not_a_500():
    """Whatever the interpreter does with absurd nesting (RecursionError on 3.13 at 20k levels,
    a parsed list on 3.14 until ~100k), the adapter must answer with IngestError, never a 500."""
    from src.adapters import parse_canonical_json
    for depth in (20000, 250000):
        with pytest.raises(IngestError):
            parse_canonical_json("[" * depth + "]" * depth)


def test_parser_failures_are_ingest_errors_without_the_cell_text():
    """parse_html raises ValueError/TypeError with the offending cell in the message; the user gets a plain 400."""
    import re
    m = re.search(r'כמות\s*</td><td style="width:25%">(\d+)', GOOD_HTML)
    bad = GOOD_HTML[:m.end(1)] + " בערך SECRET-CELL" + GOOD_HTML[m.end(1):]
    with pytest.raises(IngestError, match="unmodified export") as ei:
        ingest(bad, "x.html")
    assert "SECRET" not in str(ei.value) and ei.value.__cause__ is None and ei.value.__suppress_context__
    with pytest.raises(IngestError):
        ingest(123, "x.html")


def test_bom_prefixed_upload_is_accepted():
    canon = json.dumps(schema_skeleton()).encode()
    assert ingest(b"\xef\xbb\xbf" + canon, "p.json")[1] == "canonical-json"
    assert ingest(b"\xef\xbb\xbf" + GOOD_HTML.encode())[1] == "il-council-html"  # detection, no filename


def test_huge_invalid_array_is_a_fast_400(monkeypatch):
    """jsonschema yields one error per bad item; sorting them all took 361 MB for 100k items."""
    import time
    import server.app as app_module
    monkeypatch.setattr(app_module.limiter, "enabled", False)
    body = json.dumps({"instance": {"experiments": [1] * 200_000}})
    with app.test_client() as c:
        t0 = time.perf_counter()
        r = c.post("/api/analyze", data=body, content_type="application/json")
        elapsed = time.perf_counter() - t0
    assert r.status_code == 400
    assert elapsed < 1.0, elapsed
