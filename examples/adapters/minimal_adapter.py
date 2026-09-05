"""Minimal example adapter: a flat record from some other protocol system -> canonical instance.

Start from ``schema_skeleton()`` (every required field, filled with schema examples), then
overlay the fields your system knows. The result validates against src/schema.py and can be
POSTed as ``{"instance": ...}`` or uploaded as ``.json``. Third parties copy this file.

  python examples/adapters/minimal_adapter.py > my_protocol.json
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.adapters import item_skeleton, schema_skeleton  # noqa: E402


def to_canonical(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Map a flat one-experiment record onto the canonical schema."""
    inst = schema_skeleton()
    inst["header"].update(protocol_id=str(rec["id"]), institution=rec["institution"])
    inst["research"].update(title_en=rec["title"], title_he=rec.get("title_he", rec["title"]),
                            request_type=rec.get("request_type", "regular"))
    inst["pi"].update(first_name_en=rec["pi_first"], last_name_en=rec["pi_last"], email=rec["pi_email"])
    inst["summaries"].update({"scientific_en_≤300w": rec["summary"], "lay_he_≤150w": rec.get("lay_summary", rec["summary"])})
    inst["alternatives_search"].update(engines=list(rec.get("alt_engines", [])), queries=list(rec.get("alt_queries", [])),
                                       conclusion=rec.get("alt_conclusion", ""))
    animals = item_skeleton("animals_total")
    animals.update(species=rec["species"], strain=rec.get("strain", ""), sex=rec.get("sex", "both"), n_total=int(rec["n"]))
    inst["animals_total"] = [animals]
    exp = item_skeleton("experiments")
    exp["animals"].update(species=rec["species"], strain=rec.get("strain", ""), sex=rec.get("sex", "both"), n=int(rec["n"]))
    exp.update(severity_level_1_to_5=int(rec.get("severity", 2)))
    exp["euthanasia"].update(primary=rec.get("euthanasia_method", "CO2"))
    inst["experiments"] = [exp]
    return inst


EXAMPLE = {
    "id": 90042, "institution": "Example Institute", "title": "Tumour growth kinetics under drug X",
    "pi_first": "Ada", "pi_last": "Example", "pi_email": "ada@example.org",
    "summary": "We measure tumour growth in a xenograft model to test drug X.",
    "species": "mouse", "n": 24, "sex": "F", "severity": 3, "euthanasia_method": "CO2",
    "alt_engines": ["PubMed", "Norecopa"], "alt_queries": ["xenograft alternatives in vitro"],
    "alt_conclusion": "No validated in vitro alternative reproduces tumour-stroma interaction.",
}

if __name__ == "__main__":
    print(json.dumps(to_canonical(EXAMPLE), ensure_ascii=False, indent=2))
