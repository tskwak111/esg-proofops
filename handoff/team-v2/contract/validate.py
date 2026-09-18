"""Validate handoff fixtures, not product decisions or real source verification."""

import copy
import hashlib
import json
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parent


def read(name):
    return json.loads((ROOT / name).read_text())


def digest(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def check_packet(packet):
    sources = packet["sources"]
    ids = [source["source_id"] for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source_id")
    refs = [packet["claim"]["source_id"], packet["explanation"]["source_id"]]
    refs += [packet[side]["source_id"] for side in ("sustainability", "financial")]
    refs += packet["search"]["reviewed_source_ids"]
    if packet["c4_context"]:
        refs += packet["c4_context"]["definition_source_ids"]
        refs += packet["c4_context"]["calculation_source_ids"]
    if packet["c3_context"]:
        refs += [
            packet["c3_context"][k] for k in ("commitment_source_id", "funding_plan_source_id")
        ]
    if any(ref is not None and ref not in ids for ref in refs):
        raise ValueError("unknown source reference")
    if packet["explanation"]["search_complete"] != (packet["search"]["state"] == "complete"):
        raise ValueError("search states disagree")
    search = packet["search"]
    if search["state"] == "complete" and (
        search["failed_document_ids"]
        or not search["coverage_policy_id"]
        or not search["receipt_id"]
        or not search["required_document_ids"]
    ):
        raise ValueError("invalid complete search receipt")
    identity = packet["identity"]
    for start, end in (
        ("period_start", "period_end"),
        ("financial_period_start", "financial_period_end"),
    ):
        if (
            identity[start]
            and identity[end]
            and date.fromisoformat(identity[start]) > date.fromisoformat(identity[end])
        ):
            raise ValueError("reversed period")


def main():
    validators = {}
    for kind in ("input", "output", "policy"):
        schema = read(f"{kind}.schema.json")
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema, format_checker=FormatChecker())
        validators[kind].validate(read(f"example-{kind}.json"))
    cases = [read(str(p.relative_to(ROOT))) for p in sorted((ROOT / "examples").glob("*.json"))]
    for case in cases:
        for key, kind in (("input", "input"), ("policy", "policy"), ("expected", "output")):
            validators[kind].validate(case[key])
        check_packet(case["input"])
        result = case["expected"]
        assert result["packet_sha256"] == digest(case["input"])
        assert result["policy_sha256"] == digest(case["policy"])
        assert result["claim_id"] == case["input"]["identity"]["claim_id"]
        assert result["item"] == case["input"]["item"]
        assert set(result["source_ids"]) <= {s["source_id"] for s in case["input"]["sources"]}
    result = read("example-output.json")
    for key, value in (("status", "mismatch"), ("evidence_grade", "E3")):
        invalid = copy.deepcopy(result)
        invalid[key] = value
        assert not validators["output"].is_valid(invalid)
    assert not validators["output"].is_valid(result | {"execution_state": "blocked"})
    validators["output"].validate(result | {"execution_state": "blocked", "status": None})
    packet = read("example-input.json")
    assert not validators["input"].is_valid(packet | {"item": "C5"})
    for mutation in ("duplicate", "dangling", "coverage", "date"):
        broken = copy.deepcopy(packet)
        if mutation == "duplicate":
            broken["sources"].append(broken["sources"][0])
        elif mutation == "dangling":
            broken["claim"]["source_id"] = "missing"
        elif mutation == "coverage":
            broken["search"]["state"] = "complete"
            broken["explanation"]["search_complete"] = True
        else:
            broken["identity"]["period_start"] = "2025-01-01"
        try:
            check_packet(broken)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid packet: {mutation}")
    print(f"PASS: 3 schemas, {len(cases)} synthetic cases, hash/ref/status/stage guards")


if __name__ == "__main__":
    main()
