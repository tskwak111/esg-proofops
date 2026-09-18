"""Offline handoff contract checks; does not implement reconciliation or approve evidence."""

import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parent


def read(name):
    return json.loads((ROOT / name).read_text())


def digest(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def main():
    validators = {}
    for kind in ("input", "output", "policy"):
        schema = read(f"{kind}.schema.json")
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema)
        validators[kind].validate(read(f"example-{kind}.json"))
    result = read("example-output.json")
    assert result["packet_sha256"] == digest(read("example-input.json"))
    assert result["policy_sha256"] == digest(read("example-policy.json"))
    for key, value in (("status", "mismatch"), ("evidence_grade", "E3")):
        invalid = copy.deepcopy(result)
        invalid[key] = value
        assert not validators["output"].is_valid(invalid)
    blocked = result | {"execution_state": "blocked"}
    assert not validators["output"].is_valid(blocked)
    validators["output"].validate(blocked | {"status": None})
    packet = read("example-input.json")
    assert not validators["input"].is_valid(packet | {"item": "C5"})
    print(
        "PASS: three schemas, synthetic fixtures, hashes, grade isolation, status and stage guards"
    )


if __name__ == "__main__":
    main()
