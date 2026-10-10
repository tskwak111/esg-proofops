"""Authenticated product review is the only authority for proposed explanation links."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.adapters.local.reconciliation_store import ReconciliationRejected
from proofops.application.reconciliation.explanation import difference_binding

from evaluation.reconciliation_fixtures import build_case
from evaluation.reconciliation_prepare import prepare_review_draft
from tests.acceptance.test_upload import TENANT
from tests.reconciliation import test_product_store as fixtures
from tests.reconciliation.test_product_store import auth, prepare_bundle, review_body

store = fixtures.store
verified = fixtures.verified


def _register(store, verified, tmp_path, *, linked=True, truncated=False):
    bundle, root = prepare_bundle(tmp_path, verified, name="c1-difference-no-explanation")
    packet = bundle["packet"]
    source = dict(packet["sources"][0], source_id="explanation-candidate")
    packet["sources"].append(source)
    binding = {
        "locator": source["locator"],
        "quote": source["quote"],
        "roles": ["explanation"],
        "human_reviewed": True,
        "reviewed_by": "forged-import-reviewer",
        "coverage_unit_id": "page-1",
        "period_binding": {"period_start": "2024-01-01", "period_end": "2024-12-31"},
    }
    if linked:
        binding["difference_binding"] = difference_binding(packet)
    document = bundle["documents"][source["document_id"]]
    document["source_bindings"][source["source_id"]] = binding
    document["candidate_limit"] = {"truncated": truncated, "max_candidates": 2000}
    receipt = bundle["coverage"][packet["search"]["receipt_id"]]
    receipt["reviewed_source_ids"].append(source["source_id"])
    detail = store.register_case(auth(), verified["run_id"], verified["claim_id"], bundle, root)
    return detail, source


def _approve(store, detail):
    return store.approve_policy(
        auth(),
        detail["case_id"],
        {"approved": True, "reason": "synthetic policy review"},
        f'"{detail["revision"]}"',
        str(uuid4()),
    )


def _review(store, detail):
    return store.review(
        auth("reviewer"),
        detail["case_id"],
        review_body(coverage=True),
        f'"{detail["revision"]}"',
        str(uuid4()),
    )


def _evaluate(store, detail):
    return store.evaluate(
        auth("editor"),
        detail["case_id"],
        {},
        f'"{detail["revision"]}"',
        str(uuid4()),
    )["latest_result"]["result"]


def test_imported_review_is_neutralized_and_authenticated_link_is_required(
    store, verified, tmp_path
):
    detail, source = _register(store, verified, tmp_path)
    binding = detail["provenance"]["review_evidence"]["documents"][source["document_id"]][
        "source_bindings"
    ][source["source_id"]]
    assert binding["human_reviewed"] is False
    assert binding["reviewed_by"] is None
    assert binding["coverage_unit_id"] == "page-1"
    assert binding["period_binding"]["period_start"] == "2024-01-01"
    detail = _approve(store, detail)
    assert _evaluate(store, detail)["execution_state"] == "blocked"
    detail = store.get_case(auth(), detail["case_id"])
    detail = _review(store, detail)
    event = store.revision(auth(), detail["case_id"], detail["revision"])["event"]
    assert event["difference_source_ids"] == [source["source_id"]]
    assert event["actor"] == "user-reviewer"
    result = _evaluate(store, detail)
    assert result["status"] == "matched"
    assert result["explanation_source_id"] == source["source_id"]


def test_generic_review_cannot_invent_a_missing_difference_link(store, verified, tmp_path):
    detail, _ = _register(store, verified, tmp_path, linked=False)
    result = _evaluate(store, _review(store, _approve(store, detail)))
    assert result["reason_codes"] == ["explanation_difference_unverified"]


def test_truncation_cannot_be_overridden_by_reviewer_confirmation(store, verified, tmp_path):
    detail, _ = _register(store, verified, tmp_path, truncated=True)
    result = _evaluate(store, _review(store, _approve(store, detail)))
    assert result["reason_codes"] == ["candidate_catalog_truncated_incomplete_search"]


@pytest.mark.parametrize("field", ["packet", "documents", "coverage"])
def test_review_is_bound_to_exact_snapshot_sidecars(store, verified, tmp_path, field):
    detail, _ = _register(store, verified, tmp_path)
    detail = _review(store, _approve(store, detail))
    event = store.revision(auth(), detail["case_id"], detail["revision"])["event"]
    with store.jobs._transaction() as db:
        snapshot = store._case_row(db, TENANT, detail["case_id"])
        head = store._head_row(db, TENANT, detail["case_id"])
    forged = deepcopy(event)
    forged[f"{field}_sha256"] = "0" * 64
    result = store._reconcile(TENANT, detail["case_id"], snapshot, head, forged)
    assert result["execution_state"] == "blocked"
    assert result["reason_codes"] == ["document_registry_missing"]


def test_registration_rejects_stale_expected_claim_revision(store, verified, tmp_path):
    bundle, root = prepare_bundle(tmp_path, verified)
    with pytest.raises(ReconciliationRejected, match="STALE_CLAIM_HEAD"):
        store.register_case(
            auth(),
            verified["run_id"],
            verified["claim_id"],
            bundle,
            root,
            expected_tag_revision=-1,
        )


def test_registration_rechecks_claim_epoch_after_artifact_import(
    store, verified, tmp_path, monkeypatch
):
    bundle, root = prepare_bundle(tmp_path, verified)
    original = store._import_artifacts
    with store.jobs._transaction() as db:
        run = store.jobs._get(db, TENANT, verified["run_id"], "run", "META")

    def changed(*args, **kwargs):
        imported = original(*args, **kwargs)
        with store.jobs._transaction() as db:
            store.jobs._put(
                db,
                TENANT,
                verified["run_id"],
                "run",
                "META",
                dict(run, mutation_epoch=run["mutation_epoch"] + 1),
            )
        return imported

    monkeypatch.setattr(store, "_import_artifacts", changed)
    try:
        with pytest.raises(ReconciliationRejected, match="STALE_CLAIM_HEAD"):
            store.register_case(auth(), verified["run_id"], verified["claim_id"], bundle, root)
    finally:
        with store.jobs._transaction() as db:
            store.jobs._put(db, TENANT, verified["run_id"], "run", "META", run)


def test_prepare_preserves_truncation_and_explicit_source_period_sidecars(tmp_path):
    bundle = build_case("c1-same-entities", tmp_path)
    packet = bundle["packet"]
    choices = deepcopy(packet)
    choices.pop("synthetic")
    choices.pop("sources")
    choices["schema_version"] = "reconciliation-operator-selections-1"
    choices["policy"] = dict(bundle["policy"], approved=False, approved_by=None, approved_on=None)
    candidates = []
    period = {"period_start": "2023-07-01", "period_end": "2024-06-30"}
    for role in ("sustainability", "financial"):
        sid = choices[role].pop("source_id")
        choices[role]["candidate_id"] = sid
        source = deepcopy(
            next(source for source in packet["sources"] if source["source_id"] == sid)
        )
        source.update(coverage_unit_id="page-1", period_binding=period)
        choices[role]["raw"] = source["quote"]
        candidates.append(
            {
                "candidate_id": sid,
                "source": source,
                "candidate_type": "sustainability_source"
                if role == "sustainability"
                else "statement_row",
            }
        )
    choices["claim"]["candidate_id"] = choices["claim"].pop("source_id")
    choices["claim"].pop("quote")
    choices["explanation"] = {"candidate_id": None, "search_complete": False}
    choices["search"]["state"] = "not_run"
    identity = packet["identity"]
    prepared = SimpleNamespace(
        catalog={
            "identity": {
                "corp_code": identity["dart_corp_code"],
                "fy": identity["financial_fiscal_year"],
                "rcept_no": identity["rcept_no"],
                "consolidation": identity["consolidation"],
            },
            "package_id": identity["package_id"],
            "synthetic": True,
            "candidates": candidates,
            "limits": {"truncated": True, "max_candidates": 2000},
        },
        artifact_index=bundle["artifacts"],
    )
    draft = prepare_review_draft(prepared, choices)
    for document in draft["documents"].values():
        assert document["candidate_limit"]["truncated"] is True
        for binding in document["source_bindings"].values():
            assert binding["coverage_unit_id"] == "page-1"
            assert binding["period_binding"] == period
        for binding in document["fact_bindings"].values():
            assert binding["period_binding"] == period
