"""Browser wiring test: open /app in headless Chrome, upload a fixture, read the verdict.

An offline suite proves the Python; only a browser proves the page. This drives Chrome over the
DevTools protocol (no extra packages beyond `websocket-client`), sets the hidden file input to a
real fixture and prints what the user would see, plus every console error.

  python scripts/browser_smoke.py http://localhost:4242 examples/head-to-head/1/bad.html

Exit code 1 if the page has a JavaScript exception or no verdict rendered. Needs Google Chrome
(macOS path assumed; override with CHROME=/path/to/chrome). Nothing is stored; fixtures only.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket  # websocket-client

CHROME = os.getenv("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PORT = 9333


def main(base_url: str, fixture: str) -> int:
    fixture = str(pathlib.Path(fixture).resolve())
    profile = tempfile.mkdtemp(prefix="etiq-chrome-")
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--remote-debugging-port={PORT}",
         "--remote-allow-origins=*", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                break
            except Exception:
                time.sleep(0.2)
        else:
            print("chrome did not expose DevTools"); return 1
        ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
        mid = [0]
        console = []

        def send(method, params=None):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
            while True:
                r = json.loads(ws.recv())
                if r.get("method") == "Runtime.exceptionThrown":
                    d = r["params"]["exceptionDetails"]
                    console.append("EXCEPTION " + str(d.get("exception", {}).get("description", d.get("text")))[:300])
                elif r.get("method") == "Runtime.consoleAPICalled" and r["params"]["type"] == "error":
                    console.append("console.error " + " ".join(str(a.get("value", a.get("description", "")))[:200] for a in r["params"]["args"]))
                if r.get("id") == mid[0]:
                    return r.get("result", {})

        def ev(js):
            return send("Runtime.evaluate", {"expression": js, "returnByValue": True}).get("result", {}).get("value")

        send("Runtime.enable"); send("Page.enable"); send("DOM.enable")
        send("Page.navigate", {"url": f"{base_url.rstrip('/')}/app"}); time.sleep(2.5)
        doc = send("DOM.getDocument", {"depth": 1})
        node = send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "#file-input"})
        if not node.get("nodeId"):
            print("no #file-input on the page"); return 1
        send("DOM.setFileInputFiles", {"nodeId": node["nodeId"], "files": [fixture]}); time.sleep(4)
        verdict = ev("(document.getElementById('summary-verdict')||{}).textContent||''").strip()
        items = ev("document.querySelectorAll('#report-summary li, #checklist li, .checklist li').length")
        print("direction:", ev("document.documentElement.getAttribute('dir')+'/'+document.documentElement.lang"))
        print("verdict:", verdict or "(none)")
        print("list items rendered:", items)
        print("console:", console or "clean")
        return 0 if verdict and not any(c.startswith("EXCEPTION") for c in console) else 1
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
            chrome.wait()
        shutil.rmtree(profile, ignore_errors=True)  # nothing from the run survives, fixture or not


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
