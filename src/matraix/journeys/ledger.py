"""Single-attempt, cross-process request accounting; never contains credentials."""

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import hashlib
import sqlite3
from pathlib import Path


def binding(path, limit):
    """Public fingerprint of accounting configuration, without exposing its path."""
    return {
        "ledger_path_sha256": hashlib.sha256(
            str(Path(path).resolve()).encode()
        ).hexdigest(),
        "request_limit": int(limit),
    }


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(
        "CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, role TEXT, request_hash TEXT, status TEXT, receipt TEXT, created TEXT)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), stopped INTEGER NOT NULL, reason TEXT)"
    )
    c.execute("INSERT OR IGNORE INTO control(id,stopped) VALUES(1,0)")
    c.commit()
    return c


@contextmanager
def database(path):
    connection = connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def stop(path, reason):
    with database(path) as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "UPDATE control SET stopped=1,reason=COALESCE(reason,?) WHERE id=1",
            (reason,),
        )


def is_stopped(path):
    with database(path) as c:
        return bool(c.execute("SELECT stopped FROM control WHERE id=1").fetchone()[0])


def reserve(path, role, request_hash, limit):
    if limit < 1:
        raise ValueError("Positive overall request limit required")
    with database(path) as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT stopped FROM control WHERE id=1").fetchone()[0]:
            raise RuntimeError("Study stopped; no additional API dispatch")
        n = c.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        if n >= limit:
            raise RuntimeError("Global API request ceiling reached; no retry")
        row = c.execute(
            "INSERT INTO requests(role,request_hash,status,created) VALUES(?,?,?,?)",
            (role, request_hash, "reserved", datetime.now(timezone.utc).isoformat()),
        )
        return row.lastrowid


def finish(path, request_id, receipt):
    with database(path) as c:
        c.execute(
            "UPDATE requests SET status=?,receipt=? WHERE id=?",
            (receipt["status"], json.dumps(receipt, allow_nan=False), request_id),
        )
        if receipt["status"] == "failed":
            c.execute(
                "UPDATE control SET stopped=1,reason=COALESCE(reason,?) WHERE id=1",
                ("api_failure",),
            )


def summary(path):
    if not Path(path).exists():
        return {
            "requests": 0,
            "inflight_or_unknown": 0,
            "accepted": 0,
            "failed": 0,
            "usage_reported_tokens": 0,
            "usage_unknown_requests": 0,
        }
    with database(path) as c:
        rows = c.execute("SELECT status,receipt FROM requests").fetchall()
    receipts = [json.loads(r) for _, r in rows if r]
    result = {
        "requests": len(rows),
        "inflight_or_unknown": sum(s == "reserved" for s, _ in rows),
        "accepted": sum(s == "accepted" for s, _ in rows),
        "failed": sum(s == "failed" for s, _ in rows),
        "usage_reported_tokens": sum(
            (r.get("usage") or {}).get("total_tokens", 0) for r in receipts
        ),
        "usage_unknown_requests": sum(r.get("usage_unknown", True) for r in receipts)
        + sum(s == "reserved" for s, _ in rows),
    }
    for role in ("sut", "put"):
        selected = [r for r in receipts if r.get("role") == role]
        usage = [r.get("usage") or {} for r in selected]
        cache_known = [
            u
            for u in usage
            if "prompt_cache_hit_tokens" in u
            or "cached_tokens" in (u.get("prompt_tokens_details") or {})
        ]
        result.setdefault("roles", {})[role] = {
            "requests": len(selected),
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage),
            "cache_hit_tokens": sum(
                u.get(
                    "prompt_cache_hit_tokens",
                    (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                )
                for u in cache_known
            ),
            "cache_miss_tokens": sum(
                u.get(
                    "prompt_cache_miss_tokens",
                    u.get("prompt_tokens", 0)
                    - u.get(
                        "prompt_cache_hit_tokens",
                        (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                    ),
                )
                for u in cache_known
            ),
            "cache_usage_unknown_requests": len(selected) - len(cache_known),
            "cache_write_tokens_reported": sum(
                (u.get("prompt_tokens_details") or {}).get("cache_write_tokens", 0)
                for u in usage
            ),
            "cache_write_unknown_requests": sum(
                "cache_write_tokens" not in (u.get("prompt_tokens_details") or {})
                for u in usage
            ),
            "reasoning_tokens_reported": sum(
                (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
                for u in usage
            ),
            "duration_seconds": sum(r.get("duration_seconds", 0) for r in selected),
        }
    return result
