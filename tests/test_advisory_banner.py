"""Invariant 5: advisory framing on LLM verdicts is permanent and cannot be hidden by UI state."""
import re

import lxml.html
from markupsafe import escape

from server.app import ADVISORY_NOTICE, app


def test_advisory_present_on_every_llm_panel_and_in_print():
    with app.test_client() as c:
        html = c.get("/app").get_data(as_text=True)
    assert html.count(str(escape(ADVISORY_NOTICE))) == 4  # Layer 2 card, Layer 3 card, Layer 3 results, print footer
    assert "influenced by the protocol" in ADVISORY_NOTICE and "do not replace" in ADVISORY_NOTICE


def test_advisory_is_not_inside_any_collapsible_body():
    """The banners sit next to the result panels' headers, outside bodies the minimize button toggles."""
    with app.test_client() as c:
        doc = lxml.html.fromstring(c.get("/app").get_data(as_text=True))
    banners = doc.xpath("//*[@data-advisory or @data-advisory-print]")
    assert len(banners) == 4
    for el in banners:
        ids = {a.get("id") for a in el.iterancestors()}
        assert "llm-progress-body" not in ids and "layer3-results-body" not in ids
        assert el.get("hidden") is None


def test_no_close_button_and_css_defeats_hidden():
    css = open("server/static/css/main.css", encoding="utf-8").read()
    assert ".advisory-banner[hidden] { display: block !important; }" in css
    js = open("server/static/js/app.js", encoding="utf-8").read()
    hide = r"\.remove\(|\.hidden\s*=|style\.display|classList\.add\(['\"]hidden"
    # (a) no line that mentions the banner may also remove or hide it
    offenders = [l for l in js.splitlines() if re.search(r"advisory", l, re.I) and re.search(hide, l)]
    # (b) nor may any identifier assigned from an advisory selector be hidden anywhere in the file
    names = re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*document\.querySelector(?:All)?\([^)]*advisory", js, re.I)
    for name in names:
        offenders += re.findall(rf"\b{name}\b\s*\.\s*(?:{hide})", js)
    assert offenders == [], offenders
    assert "'Advisory only" not in js  # the wording lives in server/app.py only
