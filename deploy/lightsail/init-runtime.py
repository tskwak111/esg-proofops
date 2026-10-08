"""Create a closed private runtime config; never prints the generated secret."""

import argparse
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--origin", required=True)
p.add_argument("--event", default="dec19-event")
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
o = urlsplit(a.origin)
if (
    o.scheme != "https"
    or not o.hostname
    or o.path
    or o.query
    or o.fragment
    or o.username
    or o.password
    or "*" in a.origin
    or "\n" in a.event
    or "\r" in a.event
):
    raise SystemExit("Exact production HTTPS origin and single-line event ID required")
s = (
    (Path(__file__).parent / "runtime.env.example")
    .read_text()
    .replace("https://REPLACE_WITH_PRODUCTION_DOMAIN", a.origin)
    .replace("REPLACE_WITH_AT_LEAST_32_RANDOM_BYTES", secrets.token_urlsafe(48))
    .replace("HOSTED_EVENT_ID=dec19-event", "HOSTED_EVENT_ID=" + a.event)
)
fd = os.open(a.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(s)
print("Private 0600 runtime config created; upload/run/live flags remain closed.")
