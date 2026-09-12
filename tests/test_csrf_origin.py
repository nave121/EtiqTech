"""check_origin(): same-origin POSTs work on any port; cross-site is refused; a forwarded Host is not trusted."""
import io

import pytest

from server import app as appmod


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("PROXY_FIX", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _post(client, **headers):
    return client.post("/api/analyze", data={"file": (io.BytesIO(b"<html></html>"), "x.html")},
                       content_type="multipart/form-data", headers=headers)


def test_no_origin_header_is_same_origin(client):
    assert _post(client).status_code != 403


def test_same_origin_on_any_port_is_allowed(client):
    r = _post(client, Origin="http://localhost:5555", Host="localhost:5555")
    assert r.status_code != 403


def test_cross_site_origin_is_refused(client):
    r = _post(client, Origin="http://evil.example", Host="localhost:4242")
    assert r.status_code == 403


def test_behind_proxy_host_header_is_not_trusted(client, monkeypatch):
    monkeypatch.setenv("PROXY_FIX", "1")
    # what ProxyFix would produce from an attacker-supplied X-Forwarded-Host
    r = _post(client, Origin="http://evil.example", Host="evil.example")
    assert r.status_code == 403


def test_behind_proxy_allowed_origins_names_the_public_origin(client, monkeypatch):
    monkeypatch.setenv("PROXY_FIX", "1")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://etiq.example.org")
    assert _post(client, Origin="https://etiq.example.org", Host="etiq.example.org").status_code != 403
    assert _post(client, Origin="https://other.example.org", Host="etiq.example.org").status_code == 403
