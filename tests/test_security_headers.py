"""CSP: scripts run only with the per-request nonce; no unsafe-inline for scripts."""
import re

from server.app import app


def test_csp_uses_script_nonce_and_template_carries_it():
    with app.test_client() as c:
        r = c.get("/")
    csp = r.headers["Content-Security-Policy"]
    m = re.search(r"script-src 'self' 'nonce-([A-Za-z0-9_-]+)'", csp)
    assert m, csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]  # scripts: none; styles keep it
    assert f'nonce="{m.group(1)}"' in r.get_data(as_text=True)


def test_nonce_changes_per_request():
    with app.test_client() as c:
        a = c.get("/api/health").headers["Content-Security-Policy"]
        b = c.get("/api/health").headers["Content-Security-Policy"]
    assert a != b
