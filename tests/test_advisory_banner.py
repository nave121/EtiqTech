"""Invariant 5: advisory framing on LLM verdicts is permanent and cannot be hidden by UI state."""
from html.parser import HTMLParser

from markupsafe import escape

from server.app import ADVISORY_NOTICE, app


class _Tree(HTMLParser):
    """Records, for each advisory element, the attribute sets of all its ancestors."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.found = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.stack.append((tag, a))
        if "data-advisory" in a or "data-advisory-print" in a:
            self.found.append([x[1] for x in self.stack[:-1]])
    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def test_advisory_present_on_every_llm_panel_and_in_print():
    with app.test_client() as c:
        html = c.get("/app").get_data(as_text=True)
    assert html.count(str(escape(ADVISORY_NOTICE))) == 4  # Layer 2 card, Layer 3 card, Layer 3 results, print footer
    assert "influenced by the protocol" in ADVISORY_NOTICE and "do not replace" in ADVISORY_NOTICE


def test_advisory_is_not_inside_any_collapsible_body():
    """The banners sit next to the result panels' headers, outside bodies the minimize button toggles."""
    with app.test_client() as c:
        html = c.get("/app").get_data(as_text=True)
    t = _Tree(); t.feed(html)
    assert len(t.found) == 4
    for ancestors in t.found:
        ids = {a.get("id") for a in ancestors}
        assert "llm-progress-body" not in ids and "layer3-results-body" not in ids


def test_no_close_button_and_css_defeats_hidden():
    css = open("server/static/css/main.css", encoding="utf-8").read()
    assert ".advisory-banner[hidden] { display: block !important; }" in css
    js = open("server/static/js/app.js", encoding="utf-8").read()
    assert "advisory-banner" in js and ".remove()" not in js.split("advisoryNotice")[0].split("advisory")[-1]
