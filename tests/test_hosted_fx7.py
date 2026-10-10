"""FX7: free text-layer dates, immutable scope revisions and frozen pilot inputs."""

import json
import time
from dataclasses import replace

import pytest
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_store import HostedError

from tests import test_hosted_scope as shared_scope
from tests.test_hosted_public import actor, pdf
from tests.test_hosted_scope import install_plan


@pytest.fixture
def settings(tmp_path):
    return shared_scope.settings.__wrapped__(tmp_path)


@pytest.fixture
def store(settings):
    from proofops_api.hosted_store import HostedStore

    return HostedStore(settings)


def detect(texts, count=30):
    from evaluation.reporting_period import detect_reporting_period

    return detect_reporting_period(texts, count, "a" * 64)


def test_native_period_with_exception_and_source_offsets():
    text = (
        "보고 기간\n본 보고서는 2024년 1월 1일부터 2024년 12월 31일까지의 성과를 담았습니다. "
        "일부 성과는 2025년 상반기를 포함합니다."
    )
    result = detect({2: text})
    assert result["status"] == "detected"
    assert result["selected"] == dict(
        report_year=2024, period_start="2024-01-01", period_end="2024-12-31"
    )
    assert result["exceptions"]
    ref = result["candidates"][0]["source_ref"]
    assert ref["physical_page"] == 2
    assert ref["quote"] == text[ref["char_start"] : ref["char_end"]]
    assert ref["source_sha256"] == "a" * 64
    assert ref["verification_state"] == "inspection_only"


@pytest.mark.parametrize(
    "text",
    [
        "Reporting period: January 1, 2023 to December 31, 2023.",
        "보고기간: 2023.1.1~12.31",
        "보고 기간: 2023년 1월부터 12월까지",
        "보고 기간: 2023 회계연도",
    ],
)
def test_explicit_annual_period_formats(text):
    result = detect({30: text})
    assert result["status"] == "detected"
    assert result["selected"]["period_start"] == "2023-01-01"
    assert result["selected"]["period_end"] == "2023-12-31"


def test_ambiguous_partial_and_non_scope_years_are_not_adopted():
    assert detect({2: "보고기간: 2023 회계연도. 보고기간: 2024 회계연도."})["status"] == "ambiguous"
    assert (
        detect({2: "보고기간: 재무 및 사업 성과는 2025년 12월 31일까지입니다."})["selected"] is None
    )
    assert (
        detect({2: "목표: 2050년 탄소중립. 온실가스 검증 기간: 2024.1.1~12.31"})["selected"] is None
    )
    assert detect({15: "보고기간: 2024 회계연도"})["status"] == "not_found"
    assert detect({2: "보고기간: 2024.2.30~2024.12.31"})["selected"] is None


def test_fallback_and_manual_revision_pin_period_in_run(store, settings, tmp_path):
    from proofops_api.hosted_scope import scope_selection

    from evaluation.hosted_r108 import prepare_argv
    from evaluation.reporting_period import resolve_reporting_scope

    auth = actor(store)
    doc = store.upload(auth, pdf(3), "fx7-upload-000001", now=time.time())
    old = install_plan(store, auth, doc)
    period = resolve_reporting_scope(
        detect({}), dict(report_year=2022, period_start="2022-01-01", period_end="2022-12-31")
    )
    old["plan"]["reporting_period_detection"] = detect({})
    old["plan"]["plan_sha256"] = canonical_hash(
        {k: v for k, v in old["plan"].items() if k != "plan_sha256"}
    )
    old["reporting_scope"] = period
    old["selection"] = scope_selection(old["plan"], doc["sha256"], 3, reporting_scope=period)
    path = store.document_dir(auth.tenant_id, doc["document_id"]) / "scope-000001.json"
    store._write(path, json.dumps(old).encode())
    original_bytes = path.read_bytes()
    changed = store.edit_scope(
        auth,
        doc["document_id"],
        old["plan"]["selected_claim_pages"],
        old["plan"]["selected_evidence_pages"],
        '"1"',
        reporting_scope=dict(report_year=2023, period_start="2023-01-01", period_end="2023-12-31"),
    )
    assert changed["revision"] == 2
    assert path.read_bytes() == original_bytes
    assert changed["reporting_scope"]["origin"] == "manual"
    assert changed["selection"]["selection_sha256"] != old["selection"]["selection_sha256"]
    with pytest.raises(HostedError, match="SCOPE_CONFLICT"):
        store.edit_scope(
            auth,
            doc["document_id"],
            [1],
            [1],
            '"1"',
            reporting_scope=dict(
                report_year=2024, period_start="2024-01-01", period_end="2024-12-31"
            ),
        )
    with pytest.raises(HostedError, match="REPORTING_SCOPE_INVALID"):
        store.edit_scope(
            auth,
            doc["document_id"],
            [1],
            [1],
            '"2"',
            reporting_scope=dict(
                report_year=True, period_start="2023-01-01", period_end="2023-12-31"
            ),
        )
    with pytest.raises(HostedError, match="SCOPE_CONFLICT"):
        store.create_run(
            auth,
            doc["document_id"],
            None,
            "fx7-stale-run-001",
            now=time.time(),
            auto_scope=True,
            scope_selection_sha256=old["selection"]["selection_sha256"],
        )
    store.create_run(
        auth,
        doc["document_id"],
        None,
        "fx7-period-run-001",
        now=time.time(),
        auto_scope=True,
        scope_selection_sha256=changed["selection"]["selection_sha256"],
    )
    job = store.claim(now=time.time())
    options = store.run_options(job)
    assert options["reporting_scope"]["report_year"] == 2023
    # A later plan revision must not change the accepted run's options.
    store.edit_scope(
        auth,
        doc["document_id"],
        changed["plan"]["selected_claim_pages"],
        changed["plan"]["selected_evidence_pages"],
        '"2"',
        reporting_scope=dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31"),
    )
    assert store.run_options(job) == options
    source = tmp_path / "selected.pdf"
    source.write_bytes(pdf(3))
    argv = prepare_argv(
        source,
        tmp_path / "state",
        auth.tenant_id,
        dict(report_year=2025, period_start="2025-01-01", period_end="2025-12-31"),
        options,
    )
    assert argv[argv.index("--report-year") + 1] == "2023"
    assert argv[argv.index("--period-start") + 1] == "2023-01-01"
    assert argv[argv.index("--period-end") + 1] == "2023-12-31"


def test_generate_free_scope_uses_defaults_and_preserves_failed_status(store, settings, tmp_path):
    defaults = tmp_path / "defaults.json"
    defaults.write_text(
        json.dumps(dict(report_year=2021, period_start="2021-01-01", period_end="2021-12-31"))
    )
    store.settings = replace(settings, live_config=defaults)
    auth = actor(store)
    doc = store.upload(auth, pdf(3), "fx7-blank-upload", now=time.time())
    scope = store.generate_scope(auth, doc["document_id"])
    assert scope["plan"]["status"] == "failed"
    assert scope["reporting_scope"]["report_year"] == 2021
    assert scope["reporting_scope"]["warning"] == "보고기간 추정 실패(기본값 사용)"
    assert store.budget_totals()["event_reserved_usd"] == "0.000000"


def test_source_guard_and_no_exception_widening():
    import copy

    from evaluation.reporting_period import validate_detection

    text = "보고기간: 2024.1.1~12.31이며 일부 성과는 2025.1.1~2025.6.30까지 포함합니다."
    result = detect({2: text})
    validate_detection(result, "a" * 64)
    assert result["selected"]["period_end"] == "2024-12-31"
    assert result["exceptions"][0]["source_ref"]["quote"] == text
    bad = copy.deepcopy(result)
    bad["candidates"][0]["source_ref"]["char_start"] += 1
    with pytest.raises(ValueError):
        validate_detection(bad, "a" * 64)
    with pytest.raises(ValueError):
        validate_detection(result, "b" * 64)


def test_operator_default_publication_year_is_preserved():
    from evaluation.reporting_period import resolve_reporting_scope

    value = dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31")
    scope = resolve_reporting_scope(detect({}), value)
    assert all(scope[k] == v for k, v in value.items())


def test_http_period_revision_validation_and_tenant_guard(store, settings):
    from proofops_api.hosted import create_hosted_app

    from tests.test_hosted_public import login

    client, h, tenant, _ = login(create_hosted_app(settings), store)
    doc = client.post(
        "/v1/documents",
        content=pdf(3),
        headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "fx7-http-upload-01"},
    ).json()
    url = f"/v1/documents/{doc['document_id']}/scope-plan"
    original = client.post(url, json={}, headers=h).json()
    body = dict(
        selected_claim_pages=[1],
        selected_evidence_pages=[1],
        reporting_scope=dict(report_year=2023, period_start="2023-01-01", period_end="2023-12-31"),
    )
    assert client.post(url + "/selection", json=body, headers=h).status_code == 428
    assert (
        client.post(url + "/selection", json=body, headers=h | {"If-Match": '"1"'}).status_code
        == 200
    )
    assert (
        client.post(url + "/selection", json=body, headers=h | {"If-Match": '"1"'}).status_code
        == 412
    )
    body["reporting_scope"]["period_start"] = "2023-02-30"
    assert (
        client.post(url + "/selection", json=body, headers=h | {"If-Match": '"2"'}).status_code
        == 422
    )
    foreign, foreign_h, _, _ = login(create_hosted_app(settings), store)
    assert foreign.get(url).status_code == 404
    assert (
        foreign.post(
            url + "/selection", json=body, headers=foreign_h | {"If-Match": '"2"'}
        ).status_code
        == 404
    )
    assert original["plan"]["status"] == "failed"


def test_fallback_warning_survives_blocked_result(store, settings):
    from proofops_api.hosted_scope import scope_selection

    from evaluation.reporting_period import resolve_reporting_scope

    auth = actor(store)
    doc = store.upload(auth, pdf(3), "fx7-block-upload01", now=time.time())
    scope = install_plan(store, auth, doc)
    period = resolve_reporting_scope(
        detect({}), dict(report_year=2022, period_start="2022-01-01", period_end="2022-12-31")
    )
    scope["reporting_scope"] = period
    scope["selection"] = scope_selection(scope["plan"], doc["sha256"], 3, reporting_scope=period)
    store._write(
        store.document_dir(auth.tenant_id, doc["document_id"]) / "scope-000001.json",
        json.dumps(scope).encode(),
    )
    run = store.create_run(
        auth, doc["document_id"], None, "fx7-block-run-0001", now=time.time(), auto_scope=True
    )
    done = store.tick(now=time.time())
    assert done["status"] == "partial_blocked"
    result = store.get_result(auth.tenant_id, run["run_id"])
    assert result["pipeline"]["reporting_scope"]["warning"] == "보고기간 추정 실패(기본값 사용)"


def test_publication_dates_and_targets_do_not_make_period_ambiguous():
    result = detect(
        {
            2: "보고 기간\n본 보고서의 보고기간은 2024.1.1~12.31입니다.\n"
            "본 보고서의 보고 주기는 1년으로 이전 보고서는 2024년 6월에 발간되었습니다."
        }
    )
    assert result["status"] == "detected"
    assert result["selected"]["report_year"] == 2024
