# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| main    | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it via
[GitHub Security Advisories](https://github.com/nave121/EtiqTech/security/advisories/new).

**Do NOT open a public issue for security vulnerabilities.**

We will acknowledge receipt within 48 hours and aim to release a fix within 7 days
for critical issues.

## Security Scope

EtiqTech is designed to **run locally**. The web server (`server/app.py`) has no
authentication and should NOT be exposed to the public internet without adding an
auth layer (e.g., reverse proxy with basic auth or OAuth).

### What's in scope
- Server-side vulnerabilities (injection, path traversal, information disclosure)
- Dependency vulnerabilities
- Sensitive data exposure in fixtures or outputs

### What's out of scope
- LLM prompt injection — user-uploaded protocols are passed to the local LLM.
  Malicious content could influence LLM output. LLM verdicts are **advisory, not
  authoritative**. This is by design.
- Denial of service on localhost — the app includes rate limiting but is not
  hardened for hostile-network deployment.

## Architecture Security Notes

- **No external network calls**: The LLM runs locally via Ollama. No data is sent
  to external services.
- **No authentication**: By design for local use. See `server/app.py` header comment.
- **Rate limiting**: 10 requests/minute on analysis endpoints, 60/minute global.
- **Session expiry**: In-memory sessions expire after 1 hour.
- **CSP headers**: Content Security Policy, X-Frame-Options, X-Content-Type-Options
  are set on all responses.
- **CSRF protection**: Origin header validation on POST requests.
