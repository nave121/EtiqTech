"""Metadata-only feedback store (Phase 3.5).

Per-finding thumbs up/down keyed to a Layer 1 rule id or a Layer 2 theme, so noisy rules
can be found from data instead of guesswork. What is stored is an allowlist and nothing
else: kind, key, verdict, ruleset version, profile, timestamp. No protocol text, no
free-text comment, no session id, no user id (PRIVACY.md guarantee 2; the privacy canary
covers this file). SQLite from the standard library; the path defaults to output/ — the
one writable directory in the container. It is ephemeral there unless mounted.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("lint", "llm")
VERDICTS = ("up", "down")
PROFILES = ("default", "strict_law")  # the linter's two profiles; anything else is not a profile
_ALLOWED_FIELDS = {"kind", "key", "verdict", "ruleset_version", "profile"}
_lock = threading.Lock()


def db_path() -> Path:
    return Path(os.getenv("FEEDBACK_DB", ROOT / "output" / "feedback.sqlite"))


def feedback_enabled() -> bool:
    return os.getenv("ETIQTECH_FEEDBACK", "1").strip().lower() not in ("0", "false", "no")


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feedback ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " created_at TEXT NOT NULL,"
        " kind TEXT NOT NULL CHECK (kind IN ('lint','llm')),"
        " key TEXT NOT NULL,"
        " verdict TEXT NOT NULL CHECK (verdict IN ('up','down')),"
        " ruleset_version TEXT,"
        " profile TEXT)"
    )
    return conn


def validate(payload: Dict[str, Any], *, rule_ids: List[str], theme_keys: List[str],
             ruleset_versions: Optional[List[str]] = None) -> Dict[str, Any]:
    """Return the sanitized row or raise ValueError. Every field is an allowlist of known
    values — unknown fields, unknown keys, unknown profiles and unknown ruleset versions all
    fail loudly, so no string a client chooses can reach the store."""
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    extra = set(payload) - _ALLOWED_FIELDS
    if extra:
        raise ValueError(f"unexpected fields: {sorted(extra)}")
    kind, key, verdict = payload.get("kind"), payload.get("key"), payload.get("verdict")
    if kind not in KINDS:
        raise ValueError("kind must be 'lint' or 'llm'")
    if verdict not in VERDICTS:
        raise ValueError("verdict must be 'up' or 'down'")
    valid_keys = rule_ids if kind == "lint" else theme_keys
    if not isinstance(key, str) or key not in valid_keys:
        raise ValueError("key is not a registered rule id / theme")
    row = {"kind": kind, "key": key, "verdict": verdict}
    profile = payload.get("profile")
    if profile is not None:
        if profile not in PROFILES:
            raise ValueError("profile must be one of the linter profiles")
        row["profile"] = profile
    version = payload.get("ruleset_version")
    if version is not None:
        if ruleset_versions is None:
            from .rules import RULESET_VERSION
            ruleset_versions = [RULESET_VERSION]
        if version not in ruleset_versions:
            raise ValueError("ruleset_version is not a known ruleset")
        row["ruleset_version"] = version
    return row


def record(row: Dict[str, Any]) -> int:
    """Insert a validated row. Returns the row id."""
    with _lock, closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO feedback (created_at, kind, key, verdict, ruleset_version, profile) VALUES (?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), row["kind"], row["key"], row["verdict"],
             row.get("ruleset_version"), row.get("profile")),
        )
        return int(cur.lastrowid)


def noise_report(*, since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Per (kind, key): up/down counts and down-rate — the signal that drives rule tuning."""
    if not db_path().exists():
        return []
    _SELECT = "SELECT kind, key, SUM(verdict='up'), SUM(verdict='down'), COUNT(*) FROM feedback"
    _TAIL = " GROUP BY kind, key ORDER BY (SUM(verdict='down') * 1.0 / COUNT(*)) DESC, COUNT(*) DESC"
    with closing(_connect()) as conn:
        if since:  # two literal statements; `since` only ever travels as a bound parameter
            rows = conn.execute(_SELECT + " WHERE created_at >= ?" + _TAIL, (since,)).fetchall()
        else:
            rows = conn.execute(_SELECT + _TAIL).fetchall()
    return [{"kind": k, "key": key, "up": int(up or 0), "down": int(down or 0), "total": int(n),
             "down_rate": round((down or 0) / n, 3)} for k, key, up, down, n in rows]
