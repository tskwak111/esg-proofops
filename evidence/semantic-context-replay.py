"""Offline integrity/source-quote check for the paired context experiment.

PYTHONPATH=. uv run --no-sync python evidence/semantic-context-replay.py
Does not call a model or approve source quality/semantic bindings.
"""

import json
from pathlib import Path

from proofops.domain.provenance import canonical_hash

from evaluation.upstage_live_probe import locate_quotes

root = Path(__file__).resolve().parent
cases = json.loads((root / "semantic-context-cases.json").read_text())["cases"]
trials = json.loads((root / "semantic-context-results.json").read_text())["trials"]
assert len(cases) == len(trials) == 4
assert len({t["request_id"] for t in trials}) == 4
assert len({t["prompt_sha256"] for t in trials}) == 1
assert len({t["rule_sha256"] for t in trials}) == 1
for c, t in zip(cases, trials, strict=True):
    packet = c["packet"]
    assert c["name"] == t["name"]
    assert canonical_hash(packet) == t["packet_sha256"]
    wire = {k: v for k, v in packet.items() if k != "candidate_artifact"}
    assert canonical_hash(wire) == t["wire_sha256"]
    (claim,) = packet["candidate_artifact"]["claims"]
    span, parent = claim["span"], c["parent_span"]
    assert parent["char_start"] <= span["char_start"] < span["char_end"] <= parent["char_end"]
    relative = span["char_start"] - parent["char_start"]
    assert parent["quote"][relative : relative + len(span["quote"])] == span["quote"]
    assert packet["untrusted_document_data"]["claims"] == [dict(id="q0", text=span["quote"])]
    assert t["decision"] is None
    if t["status"] == "passed":
        (item,) = json.loads(t["response"]["content"])["claims"]
        assert item["id"] == "q0" and set(item["dimensions"]) == {"entity", "metric", "boundary"}
        for quote in item["dimensions"].values():
            if quote is not None:
                locate_quotes({"claims": [quote]}, span["quote"])
        assert t["tags"][0]["binding_status"] == "undetermined"
followup = json.loads((root / "semantic-context-fewshot.json").read_text())
baseline = next(t for t in trials if t["name"] == "performance-short")
assert followup["packet_sha256"] == baseline["packet_sha256"]
assert followup["wire_sha256"] == baseline["wire_sha256"]
assert followup["prompt_sha256"] != baseline["prompt_sha256"]
assert followup["validation_receipt"]["rule_sha256"] == baseline["rule_sha256"]
case = next(c for c in cases if c["name"] == "performance-short")
text = case["packet"]["untrusted_document_data"]["claims"][0]["text"]
(item,) = json.loads(followup["response"]["content"])["claims"]
assert item["dimensions"] == dict(entity=None, metric="약 3만 톤의 온실가스", boundary=None)
locate_quotes({"claims": [item["dimensions"]["metric"]]}, text)
assert followup["tags"][0]["binding_status"] == "undetermined"
print("PASS: four paired requests plus same-input few-shot follow-up; no semantic approval")
