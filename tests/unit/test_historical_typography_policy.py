"""Exact historical typography bytes remain replay-only, with no hash bypass."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from proofops.adapters.local.claim_source_policies import claim_source_reader, publication_reader

POLICY = Path("tests/fixtures/pipeline/claim-span-typography-history/policy.json")


def test_historical_typography_resolves_exact_verifier_bytes():
    policy = json.loads(POLICY.read_text())
    reader = claim_source_reader(policy)
    assert reader.claim_source_policy() == policy
    assert sha256(Path(reader.__file__).read_bytes()).hexdigest() == policy["wrapper_sha256"]
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_MISMATCH"):
        publication_reader(policy)


def _paths(value, path=()):
    for key, item in value.items():
        if isinstance(item, dict):
            yield from _paths(item, (*path, key))
        else:
            yield (*path, key)


@pytest.mark.parametrize("path", list(_paths(json.loads(POLICY.read_text()))))
def test_historical_policy_rejects_every_changed_leaf(path):
    policy = json.loads(POLICY.read_text())
    mutated = deepcopy(policy)
    target = mutated
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "tampered"
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_(UNKNOWN|MISMATCH)"):
        claim_source_reader(mutated)


@pytest.mark.parametrize("change", ["add", "remove"])
def test_historical_policy_rejects_changed_keys(change):
    policy = json.loads(POLICY.read_text())
    if change == "add":
        policy["extra"] = None
    else:
        policy.pop("rendered_fold_entries")
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        claim_source_reader(policy)


def test_historical_verifier_tamper_is_rejected(monkeypatch):
    policy = json.loads(POLICY.read_text())
    reader = claim_source_reader(policy)
    frozen_path = Path(reader.__file__)
    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: b"tampered" if path == frozen_path else original(path)
    )
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        claim_source_reader(policy)
