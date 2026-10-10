"""Pre-dispatch controls; usage polling is not an atomic global reservation."""

import hashlib
import json
import math
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from time import time as monotonic


class LiveError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


def check_enabled():
    if os.getenv("LIVE_DISABLED") == "1":
        raise LiveError(503, "LIVE_DISABLED")


def _setting(name, default, *, integer=False):
    try:
        value = int(os.getenv(name, default)) if integer else float(os.getenv(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except ValueError as exc:
        raise LiveError(503, "LIMIT_CHECK_UNAVAILABLE") from exc


def daily_usage():
    """GET /key usage_daily is key-wide USD usage, including other models on that key.

    https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key
    No caching: every admitted request checks before any Upstage/model dispatch.
    """
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise LiveError(503, "LIMIT_CHECK_UNAVAILABLE")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read(65_537)
        if len(raw) > 65_536:
            raise ValueError
        value = json.loads(raw)["data"]["usage_daily"]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError
        return value
    except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError) as exc:
        raise LiveError(503, "LIMIT_CHECK_UNAVAILABLE") from exc


def check_limits(forwarded_for: str):
    daily = _setting("LIVE_DAILY_LUNA_USD", "0.50")
    per_ip = _setting("LIVE_IP_PER_MINUTE", "6", integer=True)
    total = _setting("LIVE_TOTAL_PER_MINUTE", "20", integer=True)
    ip = forwarded_for.split(",", 1)[0].strip() or "unknown"
    # Serverless instances must share an atomic store; never silently fall back to RAM.
    if os.getenv("VERCEL"):
        return shared_admission(ip, per_ip, total, daily)
    ledger = Path(
        os.getenv(
            "LIVE_LIMITS_DB",
            str(Path(__file__).resolve().parents[1] / ".local/live-limits.sqlite3"),
        )
    )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(ledger, timeout=5) as db:
            db.execute("CREATE TABLE IF NOT EXISTS admissions (at REAL, client TEXT)")
            db.execute("BEGIN IMMEDIATE")
            now = monotonic()
            db.execute("DELETE FROM admissions WHERE at<=?", (now - 60,))
            count, client_count = db.execute(
                "SELECT count(*),coalesce(sum(client=?),0) FROM admissions", (ip,)
            ).fetchone()
            if count >= total or client_count >= per_ip:
                raise LiveError(429, "RATE_LIMITED")
            db.execute("INSERT INTO admissions VALUES (?,?)", (now, ip))
    except sqlite3.Error as exc:
        raise LiveError(503, "LIMIT_CHECK_UNAVAILABLE") from exc
    if daily_usage() >= daily:
        raise LiveError(429, "DAILY_LIMIT")


def shared_admission(ip, per_ip, total, daily):
    url, token = os.getenv("LIVE_REDIS_REST_URL", ""), os.getenv("LIVE_REDIS_REST_TOKEN", "")
    if not url.startswith("https://") or not token:
        raise LiveError(503, "LIMIT_CHECK_UNAVAILABLE")
    if daily_usage() >= daily:
        raise LiveError(429, "DAILY_LIMIT")
    # Reserve the largest supported request (including parsing) before any paid call.
    # Failed/unknown calls retain their reservation until the next UTC day.
    script = """
    local now=tonumber(ARGV[1]); local floor=now-60
    redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',floor)
    redis.call('ZREMRANGEBYSCORE',KEYS[2],'-inf',floor)
    if redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[2])
      or redis.call('ZCARD',KEYS[2])>=tonumber(ARGV[3]) then return 1 end
    local spent=tonumber(redis.call('GET',KEYS[3]) or '0')
    if spent+123000>tonumber(ARGV[4]) then return 2 end
    redis.call('ZADD',KEYS[1],now,ARGV[5]); redis.call('ZADD',KEYS[2],now,ARGV[5])
    redis.call('EXPIRE',KEYS[1],61); redis.call('EXPIRE',KEYS[2],61)
    redis.call('INCRBY',KEYS[3],123000); redis.call('EXPIRE',KEYS[3],172800)
    return 0
    """
    from uuid import uuid4

    now = monotonic()
    body = [
        "EVAL",
        script,
        3,
        "{live}:all",
        "{live}:ip:" + hashlib.sha256(ip.encode()).hexdigest(),
        "{live}:day:" + str(int(now // 86400)),
        now,
        total,
        per_ip,
        int(_setting("LIVE_DAILY_TOTAL_USD", "0.50") * 1_000_000),
        uuid4().hex,
    ]
    request = urllib.request.Request(
        url.rstrip("/"),
        json.dumps(body).encode(),
        {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.loads(response.read(65536))["result"]
        if type(result) is not int or result not in (0, 1, 2):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LiveError(503, "LIMIT_CHECK_UNAVAILABLE") from exc
    if result:
        raise LiveError(429, "RATE_LIMITED" if result == 1 else "DAILY_LIMIT")
