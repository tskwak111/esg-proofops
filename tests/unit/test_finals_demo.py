"""Offline checks of finals money limits, shared ledgers and frozen CLI settings."""

import io
import json
import os
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from scripts.finals_demo import FinalsBudget, parse_bound, pilot_argv


@pytest.mark.parametrize("configured", [None, "1", "4", "16"])
def test_finals_concurrency_defaults_to_16_and_preserves_operator_cap(monkeypatch, configured):
    from scripts.finals_demo import configure_concurrency

    monkeypatch.delenv("LOCAL_LLM_MAX_WORKERS", raising=False)
    if configured is not None:
        monkeypatch.setenv("LOCAL_LLM_MAX_WORKERS", configured)
    assert configure_concurrency() == int(configured or "16")
    assert int(os.environ["LOCAL_LLM_MAX_WORKERS"]) == int(configured or "16")


@pytest.mark.parametrize("configured", ["", "0", "17", "nan", "1.5"])
def test_finals_invalid_concurrency_fails_before_launch(monkeypatch, configured):
    from scripts.finals_demo import configure_concurrency

    monkeypatch.setenv("LOCAL_LLM_MAX_WORKERS", configured)
    with pytest.raises(ValueError, match="LOCAL_LLM_CONFIGURATION_INVALID"):
        configure_concurrency()


def test_main_checks_concurrency_before_state_or_paid_setup(monkeypatch):
    import sys

    from scripts.finals_demo import main

    monkeypatch.setenv("LOCAL_LLM_MAX_WORKERS", "17")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "finals",
            "--root",
            "/unused",
            "--run-root",
            "/unused",
            "--port",
            "1",
            "--kakao-port",
            "2",
        ],
    )
    with pytest.raises(ValueError, match="LOCAL_LLM_CONFIGURATION_INVALID"):
        main()


def test_16_concurrent_finals_reservations_cannot_overbook(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    fence = budget(tmp_path)
    fence.reserve(Decimal("0.45"))

    def reserve(_):
        try:
            # Separate instances share only the persistent file lock.
            reopened = FinalsBudget(fence.spend_path, fence.ledgers, fence.events_path)
            reopened.reserve(Decimal("0.02"))
            return True
        except ValueError as error:
            assert str(error) == "R108_FINALS_BUDGET_EXHAUSTED"
            return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(reserve, range(16))) == 2
    entry = json.loads(fence.spend_path.read_text())["executions"][0]
    assert Decimal(entry["reserved_usd"]) == Decimal("0.49")


def budget(tmp_path):
    spend = tmp_path / "spend.json"
    spend.write_text(json.dumps(dict(cumulative_usd="2", limit_usd="10", executions=[])))
    ledgers = {}
    for provider in ("upstage", "openrouter"):
        path = tmp_path / f"{provider}.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("create table probe_calls(request_id text, committed text, receipt text)")
        ledgers[provider] = path
    return FinalsBudget(spend, ledgers, tmp_path / "calls.jsonl")


def test_reservations_persist_across_launches_and_block_before_dispatch(tmp_path):
    fence = budget(tmp_path)
    fence.reserve(Decimal("0.49"))
    reopened = FinalsBudget(fence.spend_path, fence.ledgers, fence.events_path)
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        reopened.reserve(Decimal("0.02"))
    assert json.loads(fence.spend_path.read_text())["executions"][0]["reserved_usd"] == "0.49"


def test_guard_settles_real_ledger_charge_and_does_not_recharge_cache(tmp_path):
    fence = budget(tmp_path)
    probe = SimpleNamespace(ledger=fence.ledgers["openrouter"])

    def original(probe, *, request_id):
        with sqlite3.connect(probe.ledger) as db:
            db.execute("insert or ignore into probe_calls values (?, '0.001', '{}')", (request_id,))
        return "receipt"

    call = fence.guarded(original, "openrouter", lambda a, k: Decimal("0.02"))
    assert call(probe, request_id="one") == "receipt"
    assert call(probe, request_id="one") == "receipt"
    data = json.loads(fence.spend_path.read_text())
    assert data["cumulative_usd"] == "2.001"
    assert data["executions"][0]["delta_usd"] == "0.001"
    assert data["executions"][0]["reserved_usd"] == "0.00"


def test_unsettled_parser_charge_is_retained_and_fences_later_calls(tmp_path):
    fence = budget(tmp_path)
    probe = SimpleNamespace(ledger=fence.ledgers["upstage"])

    def failed(probe, *, request_id):
        with sqlite3.connect(probe.ledger) as db:
            db.execute("insert into probe_calls values (?, '1.00', null)", (request_id,))
        raise ValueError("UPSTAGE_REQUEST_FAILED")

    call = fence.guarded(failed, "upstage", lambda a, k: Decimal("0.022"))
    with pytest.raises(ValueError, match="UPSTAGE_REQUEST_FAILED"):
        call(probe, request_id="one")
    with pytest.raises(ValueError, match="UNSETTLED_RETRY_FORBIDDEN"):
        call(probe, request_id="one")
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        fence.reserve(Decimal("0.02"))
    assert json.loads(fence.spend_path.read_text())["cumulative_usd"] == "3.00"
    assert fence.unsettled() == Decimal("1.00")


def test_cumulative_limit_includes_old_unsettled_calls(tmp_path):
    fence = budget(tmp_path)
    with sqlite3.connect(fence.ledgers["upstage"]) as db:
        db.execute("insert into probe_calls values ('old', '8', null)")
    with pytest.raises(ValueError, match="CUMULATIVE_BUDGET_EXHAUSTED"):
        fence.reserve(Decimal("0.02"))


def test_other_ledger_refused_before_dispatch(tmp_path):
    fence = budget(tmp_path)
    other = tmp_path / "other.sqlite3"
    other.touch()
    call = fence.guarded(
        lambda *a, **k: pytest.fail("must not dispatch"), "openrouter", lambda a, k: Decimal("0.02")
    )
    with pytest.raises(ValueError, match="SHARED_LEDGER_REQUIRED"):
        call(SimpleNamespace(ledger=other), request_id="one")


def test_parse_requires_two_pages_at_most_and_reserves_the_selected_mode_price():
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    assert parse_bound((stream.getvalue(),), {}) == Decimal("0.022")
    assert parse_bound((stream.getvalue(),), {"mode": "enhanced"}) == Decimal("0.066")
    with pytest.raises(ValueError, match="PARSE_MODE_INVALID"):
        parse_bound((stream.getvalue(),), {"mode": "unpriced"})
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    with pytest.raises(ValueError, match="TWO_PAGE_SCOPE_REQUIRED"):
        parse_bound((stream.getvalue(),), {})


def test_new_session_uses_third_profile_without_invoke_or_stale_pages():
    template = [
        "pilot",
        "--pdf",
        "saved.pdf",
        "--state",
        "saved-state",
        "--pages",
        "19,23,72",
        "--claim-pages",
        "19,23",
        "--report-year",
        "2025",
        "--period-start",
        "old",
        "--period-end",
        "old",
        "--relation-profile",
        "occurrence-v3",
        "--claim-source-profile",
        "glyph-alignment-v1",
        "--display-text-profile",
        "glyph-joined-display-v1",
        "--llm-provider",
        "openrouter",
    ]
    argv = pilot_argv(
        template,
        pdf=Path("unknown.pdf"),
        state=Path("private/live"),
        port=8806,
        root=Path("/authorized"),
    )
    assert template[template.index("--pages") + 1] == "19,23,72"
    assert argv[argv.index("--pages") + 1] == "66,67"
    assert "--claim-pages" not in argv
    assert argv[argv.index("--key-file") + 1] == "/authorized/.env.openrouter.local"
    assert "--serve-worker" in argv
    assert "--invoke" not in argv and "--resume" not in argv


def test_fresh_worker_session_serves_before_claims_without_paid_bootstrap(tmp_path, monkeypatch):
    import sys

    import uvicorn
    from fastapi.testclient import TestClient

    from evaluation import local_upstage_pilot as pilot
    from evaluation import serve_worker

    pdf = tmp_path / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    key = tmp_path / "test-key.env"
    key.write_text("OPENROUTER_API_KEY=test-only-no-dispatch\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pilot",
            "--pdf",
            str(pdf),
            "--state",
            str(tmp_path / "state"),
            "--pages",
            "1",
            "--report-year",
            "2024",
            "--period-start",
            "2024-01-01",
            "--period-end",
            "2024-12-31",
            "--parser",
            "local",
            "--vision-parse",
            "off",
            "--serve",
            "--serve-worker",
            "--key-file",
            str(key),
            "--port",
            "8899",
        ],
    )
    observed = []

    def start(build, service, tenant):
        runs = serve_worker.eligible_runs(service, tenant)
        assert len(runs) == 1 and runs[0]["status"] == "queued"
        # The real start_background excludes these preexisting initial runs.
        observed.append("unprocessed initial run")
        return SimpleNamespace(is_alive=lambda: True, join=lambda **k: None), SimpleNamespace(
            set=lambda: None
        )

    def serve(app, **kwargs):
        with TestClient(app, base_url="https://localhost:8899") as client:
            login = next(
                route.path
                for route in app.routes
                if getattr(route, "path", "").startswith("/__local/")
            )
            response = client.get(login, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/documents/new"
            assert client.get("/local/submission").json()["worker_enabled"] is True
            assert client.get("/documents/new").status_code == 200
            options = client.get("/v1/runtime-options").json()
            session = client.get("/v1/session").json()
            checked = client.post(
                "/v1/preflight",
                json={
                    "runtime_binding_id": options["runtime_bindings"][0]["id"],
                    "consent_profile_id": options["consent_profiles"][0]["id"],
                    "include_live_model_probe": False,
                },
                headers={
                    "Origin": "http://localhost:8899",
                    "X-CSRF-Token": session["csrf_token"],
                    "Idempotency-Key": "test-f8-local-preflight",
                },
            )
            assert checked.status_code == 200
            assert checked.json()["ready"] is True, checked.json()["checks"]
        observed.append("live web served")

    monkeypatch.setattr(serve_worker, "start_background", start)
    monkeypatch.setattr(uvicorn, "run", serve)
    assert pilot.main() == 0
    assert observed == ["unprocessed initial run", "live web served"]


@pytest.mark.parametrize(
    "change", [None, "hash", "expired", "role", "endpoint", "purpose", "foreign", "live"]
)
def test_http_luna_preflight_requires_exact_local_approved_binding(change):
    from proofops_agent.upstage_extraction import _profile_with_options

    from tests.acceptance.test_preflight import http_client
    from tests.integration.test_upstage_runtime import profiles

    client, payload, artifacts = http_client()
    runtime, consent = profiles()
    runtime.update(
        provider="openrouter",
        model_id="openai/gpt-6-luna",
        model_sha256=_profile_with_options("openai/gpt-6-luna", wire_policy_version=2).model_sha256,
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        budget_limit_usd="5.00",
    )
    consent["provider"] = "openrouter"
    if change == "hash":
        runtime["model_sha256"] = "0" * 64
    elif change == "expired":
        consent["expires_at"] = "2026-09-08T00:00:00Z"
    elif change == "role":
        runtime["role"] = "tagger"
    elif change == "endpoint":
        runtime["endpoint"] = "https://unapproved.example"
    elif change == "purpose":
        runtime["purpose"] = "production"
    elif change == "foreign":
        runtime["tenant_id"] = "22222222-2222-4222-8222-222222222222"
    elif change == "live":
        payload["include_live_model_probe"] = True
    artifacts[("runtime", payload["runtime_binding_id"])].clear()
    artifacts[("runtime", payload["runtime_binding_id"])].update(runtime)
    artifacts[("consent", payload["consent_profile_id"])].clear()
    artifacts[("consent", payload["consent_profile_id"])].update(consent)
    checked = client.post("/v1/preflight", json=payload)
    if change == "foreign":
        assert checked.status_code == 404
    else:
        assert checked.status_code == 200
        assert checked.json()["ready"] is (change is None)
        if change == "purpose":
            assert any(check["name"] == "account_permission" for check in checked.json()["checks"])
