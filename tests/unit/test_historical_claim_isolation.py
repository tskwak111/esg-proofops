"""Historical replay cannot mutate the validator or policy of new runs."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from proofops.adapters.local import claim_source_policies as policies
from proofops.adapters.local import claim_source_verification as current_base
from proofops.adapters.local import claim_span_typography as current_typography
from proofops.application import claims

POLICY = Path("tests/fixtures/pipeline/claim-span-typography-history/policy.json")


def test_historical_reader_executes_frozen_validator(monkeypatch):
    historical = policies.claim_source_reader(json.loads(POLICY.read_text()))
    assert historical.base.claim_validation is not claims
    assert historical.baseline.base is historical.base
    assert historical.baseline.baseline.base is historical.base

    def reject_current(*args, **kwargs):
        raise AssertionError("current validator was used")

    monkeypatch.setattr(claims, "validate_extraction_response", reject_current)
    assert historical.base._unique_quote("Emissions fell 10%.", "Emissions fell 10%.")
    with pytest.raises(AssertionError, match="current validator was used"):
        current_base._unique_quote("Emissions fell 10%.", "Emissions fell 10%.")


def test_modified_frozen_validator_fails_closed(monkeypatch):
    policy = json.loads(POLICY.read_text())
    historical = policies.claim_source_reader(policy)
    frozen = Path(historical.base.claim_validation.__file__)
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda p: b"tampered" if p == frozen else original(p))
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        policies.claim_source_reader(policy)
    assert policies.publication_reader(current_base.claim_source_policy()) is current_base


def test_parallel_historical_loads_leave_current_modules_and_policy_unchanged():
    before = current_typography.claim_source_policy()
    dependencies = (
        current_typography.base,
        current_typography.baseline,
        current_base.claim_validation,
    )
    policy = json.loads(POLICY.read_text())

    def replay_and_publish(_):
        reader = policies.claim_source_reader(policy)
        assert reader.claim_source_policy() == policy
        assert policies.publication_reader(before) is current_typography
        assert current_typography.claim_source_policy() == before

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(replay_and_publish, range(12)))
    assert dependencies == (
        current_typography.base,
        current_typography.baseline,
        current_base.claim_validation,
    )
    assert current_base.claim_validation is claims
