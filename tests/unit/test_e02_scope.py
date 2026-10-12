"""E02 is explicit opt-in; old scope hashes/claim choices keep their meaning."""

from copy import deepcopy

import pytest
from proofops.application.evidence.assurance_catalog import POLICY_SHA256

from evaluation.report_scope import ASSURANCE_VERSION, build_plan, validate_selection
from tests.unit.test_report_scope import study, texts


def source():
    values = texts()
    values[55] += "\nScope\nISAE 3000\nSigned on 2026-06-01"
    values[56] = "Exclusions\n" + "Overseas facility excluded. " * 5
    values[57] = "GRI Content Index\nReferences 5-29"
    return values


def test_opt_in_selects_the_following_exclusions_and_preserves_claim_pages():
    values = source()
    old = build_plan(study(), values)
    frozen = deepcopy(old)
    new = build_plan(study(), values, ranking_policy=ASSURANCE_VERSION)
    assert old == frozen
    assert new["selected_claim_pages"] == old["selected_claim_pages"]
    assert {55, 56} <= set(new["evidence_only_pages"])
    assert new["policy_sha256"] != old["policy_sha256"]
    assert new["assurance_discovery"]["policy_sha256"] == POLICY_SHA256
    assert new["source_quality"] == "unverified"
    checked = validate_selection(new, "a" * 64, 60)
    assert checked["assurance_discovery_sha256"] == new["assurance_discovery"]["discovery_sha256"]
    assert checked["evidence_bundle_status"] == "candidate_only"


def test_selection_edits_cannot_split_an_opinion_bundle():
    plan = build_plan(study(), source(), ranking_policy=ASSURANCE_VERSION)
    plan["selected_evidence_pages"].remove(56)
    with pytest.raises(ValueError, match="partial assurance bundle"):
        validate_selection(plan, "a" * 64, 60)


def test_unknown_new_reader_version_is_rejected():
    plan = build_plan(study(), source(), ranking_policy=ASSURANCE_VERSION)
    plan["version"] = "E02-v999"
    with pytest.raises(ValueError, match="unsupported scope policy"):
        validate_selection(plan, "a" * 64, 60)
