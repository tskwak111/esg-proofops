"""Provider causes survive fencing while uncertain money stays reserved."""

import time
from decimal import Decimal

import pytest
from proofops_api.hosted_store import HostedStore

from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


@pytest.mark.parametrize(
    "provider,raw,expected",
    [
        ("upstage-parse", "UPSTAGE_API_KEY_IS_NOT_ALLOWED", "PROVIDER_CREDIT_EXHAUSTED"),
        ("upstage-ocr", "UPSTAGE_HTTP_401", "PROVIDER_AUTH_FAILED"),
        ("upstage-parse", "UPSTAGE_HTTP_403", "PROVIDER_ACCESS_DENIED"),
        ("upstage-ocr", "UPSTAGE_HTTP_429", "PROVIDER_RATE_LIMITED"),
        ("upstage-parse", "UPSTAGE_HTTP_503", "PROVIDER_UNAVAILABLE"),
    ],
)
def test_provider_error_retained_in_run_and_log(settings, caplog, provider, raw, expected):
    store, auth, job = job_setup(settings)

    def rejected(_):
        raise ValueError(raw)

    with pytest.raises(ValueError, match=raw):
        store.dispatch(
            job, provider, "pa1-call", "a" * 64, Decimal("0.011"), rejected, now=time.time()
        )
    run = store.get_run(auth.tenant_id, job["run_id"])
    assert run["status"] == "accounting_pending"
    assert run["error_code"] == expected
    assert run["error_message"]
    assert raw in caplog.text and expected in caplog.text
    with store.transaction() as db:
        cost = db.execute("SELECT bound,actual,status FROM deletion.costs").fetchone()
        assert tuple(cost) == (11000, None, "accounting_pending")
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"
    assert HostedStore(settings).get_run(auth.tenant_id, job["run_id"])["error_code"] == expected


def test_late_provider_error_does_not_replace_cancellation(settings):
    store, auth, job = job_setup(settings)

    def cancelled(_):
        store.cancel(auth, job["run_id"], now=time.time())
        raise ValueError("UPSTAGE_HTTP_401")

    with pytest.raises(ValueError):
        store.dispatch(
            job, "upstage-ocr", "pa1-call", "a" * 64, Decimal("0.011"), cancelled, now=time.time()
        )
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "cancelled"


def test_http_error_body_is_bounded_and_redacted():
    from proofops.adapters.local.provider_errors import upstage_http_error

    class Response:
        status = 403

        def read(self, limit):
            assert limit == 4097
            return b'{"error":{"code":"api_key_is_not_allowed","message":"secret"}}'

    assert str(upstage_http_error(Response())) == "UPSTAGE_API_KEY_IS_NOT_ALLOWED"


def test_openai_quota_has_specific_display_without_rewriting_old_code(settings):
    store, auth, job = job_setup(settings)
    with pytest.raises(ValueError):
        store.dispatch(
            job,
            "openai",
            "pa1-call",
            "a" * 64,
            Decimal("0.011"),
            lambda _: (_ for _ in ()).throw(ValueError("OPENAI_INSUFFICIENT_QUOTA")),
            now=time.time(),
        )
    run = store.get_run(auth.tenant_id, job["run_id"])
    assert run["error_code"] == "OPENAI_INSUFFICIENT_QUOTA"
    assert run["provider_error_code"] == "PROVIDER_CREDIT_EXHAUSTED"
    assert "크레딧" in run["provider_error_message"]
