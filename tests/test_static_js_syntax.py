"""Every script the app serves must at least parse.

2026-09-13: a comment added to server/static/js/app.js in a docs commit swallowed the rest of the
line; the browser dropped the whole script and the upload button did nothing. No test loaded the
JavaScript, the reviewers read Python, and the live check hit the API instead of the page.
`node --check` is a parse, not a run, but it is exactly the class of break that shipped.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "server" / "static" / "js").glob("*.js"))
NODE = shutil.which("node")


def test_there_are_scripts_to_check():
    assert SCRIPTS, "server/static/js is empty; the app has no client code?"


@pytest.mark.skipif(NODE is None, reason="node is not installed; CI runners have it")
@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_served_script_parses(path):
    proc = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_app_shell_is_english_ltr():
    """The UI copy is English (design commits 1-9); the document direction must match it.
    Hebrew protocol values inside English sentences render correctly via Unicode bidi."""
    html = (ROOT / "server" / "templates" / "app.html").read_text(encoding="utf-8")
    assert '<html lang="en" dir="ltr">' in html
