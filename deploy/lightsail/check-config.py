"""Validate private env file without evaluating shell or exposing its contents."""

import stat
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

path = Path(sys.argv[1])
if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
    raise SystemExit("runtime.env must be a regular non-symlink 0600 file")
env = {}
for line in path.read_text().splitlines():
    if not line or line.startswith("#"):
        continue
    k, sep, v = line.partition("=")
    if not sep or k in env or any(c in v for c in "\n\r$`") or v != v.strip():
        raise SystemExit(
            "Unsupported env syntax; use literal KEY=value without quotes/interpolation"
        )
    env[k] = v
origin = urlsplit(env.get("APP_ORIGIN", ""))
if (
    origin.scheme != "https"
    or not origin.hostname
    or origin.username
    or origin.password
    or origin.path
    or origin.query
    or origin.fragment
    or "*" in origin.netloc
    or "REPLACE" in origin.netloc
):
    raise SystemExit("Set exact verified production HTTPS APP_ORIGIN")
if (
    len(env.get("HOSTED_SESSION_SECRET", "").encode()) < 32
    or "REPLACE" in env["HOSTED_SESSION_SECRET"]
):
    raise SystemExit("Generate session secret locally; preserve it on later deployments")
if not env.get("HOSTED_EVENT_ID") or env.get("LIVE_DISABLED") not in ("true", "false"):
    raise SystemExit("Set event ID and explicit LIVE_DISABLED=true|false")
if env["LIVE_DISABLED"] == "false" and (
    env.get("ANALYSIS_BACKEND") != "r108"
    or not Path(env.get("HOSTED_LIVE_CONFIG", "")).is_absolute()
):
    raise SystemExit("Live opt-in requires r108 backend and absolute private operator config")
for k in ("HOSTED_ACCEPT_UPLOADS", "R108_ACCEPT_NEW_RUNS"):
    if env.get(k) not in ("true", "false"):
        raise SystemExit("Set explicit acceptance flags")
if env["HOSTED_ACCEPT_UPLOADS"] == "true" and not env.get("HOSTED_CONSENT_VERSION"):
    raise SystemExit("Upload consent required")
# DEC-22 defaults; an operator may raise the event ceiling only with an explicit,
# separately approved HOSTED_EVENT_USD_CEILING (DEC-65: user approved USD15 on 2026-10-14).
event_ceiling = env.get("HOSTED_EVENT_USD_CEILING", "7")
for k, cap in [
    ("HOSTED_RUN_USD", "1.0"),
    ("HOSTED_DAY_USD", "7"),
    ("HOSTED_EVENT_USD", event_ceiling),
]:
    amount = Decimal(env[k])
    if not amount.is_finite() or not 0 < amount <= Decimal(cap):
        raise SystemExit("DEC-22 cost cap exceeded")
print("Private runtime config validated (values redacted).")
