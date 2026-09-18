"""Offline replay of frozen synthetic development cases; no model/network calls.

Run: PYTHONPATH=. uv run --no-sync python evidence/semantic-capability-replay.py
"""

import json
from pathlib import Path

from proofops.domain.provenance import canonical_hash

from evaluation.metrics.elements import ElementFact, element_metrics
from evaluation.upstage_live_probe import locate_quotes

root = Path(__file__).resolve().parent
cases = json.loads((root / "semantic-capability-cases.json").read_text())["cases"]
record = json.loads((root / "semantic-capability-results.json").read_text())
expected = {c["id"]: c for c in cases}
positive = [
    ElementFact(c["id"], f, v, False)
    for c in cases
    for f, v in c["expected"].items()
    if v is not None
]
assert len(positive) == 8
assert element_metrics([], positive)[1].value == 0
for trial in record["trials"]:
    assert trial["cases_sha256"] == canonical_hash(cases)
    raw = trial["response"]["content"]
    if not trial["json_mode"]:
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            continue
        raise AssertionError("archived non-JSON-mode response unexpectedly parses")
    payload = json.loads(raw)
    assert set(payload) == {"claims"}
    assert len(payload["claims"]) == len(expected)
    assert {c["id"] for c in payload["claims"]} == set(expected)
    for c in payload["claims"]:
        assert set(c) == {"id", "dimensions"}
        assert c["dimensions"] == expected[c["id"]]["expected"]
        for quote in c["dimensions"].values():
            if quote is not None:
                locate_quotes({"claims": [quote]}, expected[c["id"]]["text"])
print("PASS: 8 explicit facts, 10 required nulls, all-null recall 0; malformed trial rejected")
