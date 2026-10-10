"""Transport-only operations tests: counters, quota stops, retries and secret masking."""

import json
import traceback
from urllib.parse import quote, quote_plus

import pytest
from proofops.adapters.dart.client import DartClient, DartError, DartRateLimitError, redact_api_key
from proofops.adapters.dart.filings import list_annual_filings


def request(client):
    return client.list_filings("00126380", "20250101", "20251231")


@pytest.mark.parametrize(
    "response,reason",
    [
        ((429, {"Retry-After": "untrusted secret"}, b"secret"), "http_429"),
        ((200, {}, b'{"status":"020","message":"secret"}'), "dart_020"),
    ],
)
def test_limits_pause_without_retry_and_require_explicit_resume(response, reason):
    responses = [response, (200, {}, b'{"status":"013"}')]
    client = DartClient(api_key="secret", transport=lambda *a, **k: responses.pop(0))
    with pytest.raises(DartRateLimitError) as error:
        request(client)
    assert "secret" not in "".join(traceback.format_exception(error.value))
    assert client.request_count == 1
    with pytest.raises(DartRateLimitError):
        request(client)
    assert client.request_count == 1
    diagnostics = client.diagnostics
    assert diagnostics["retry_count"] == 0
    assert diagnostics["rate_limit_reason"] == reason
    assert diagnostics["rate_limit_count"] == 1
    assert "reset" in diagnostics["resume_guidance"]
    assert "secret" not in json.dumps(diagnostics)
    diagnostics["request_count"] = 1000
    assert client.request_count == 1
    client.resume_rate_limit()
    assert request(client)["status"] == "013"
    assert client.request_count == 2
    assert client.diagnostics["rate_limit_reason"] is None


@pytest.mark.parametrize(
    "body",
    [
        b'{"status":"020","message":"secret"}',
        b"<result><status>020</status><message>secret</message></result>",
    ],
)
def test_archive_error_formats_pause(body):
    client = DartClient(api_key="secret", transport=lambda *a, **k: (200, {}, body))
    with pytest.raises(DartRateLimitError):
        client.download_document("20250313000532")
    assert client.diagnostics["rate_limit_reason"] == "dart_020"
    assert client.diagnostics["rate_limit_count"] == 1


def test_transport_and_server_retries_count_actual_attempts(monkeypatch):
    sleeps = []
    monkeypatch.setattr("proofops.adapters.dart.client.time.sleep", sleeps.append)
    attempts = 0

    def transport(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("offline transient")
        if attempts == 2:
            return 503, {}, b"unavailable"
        return 200, {}, b'{"status":"013"}'

    client = DartClient(api_key="secret", transport=transport, max_retries=2, retry_backoff=1)
    assert request(client)["status"] == "013"
    assert client.request_count == 3
    assert client.diagnostics["retry_count"] == 2
    assert sleeps == [1, 2]
    with pytest.raises(ValueError):
        client.list_filings("bad", "20250101", "20251231")
    assert client.request_count == 3


def test_exhausted_transport_masks_raw_and_encoded_credentials():
    secret = "key +/=?secret"

    def transport(*args, **kwargs):
        raise OSError(f"failed {secret} {quote(secret, safe='')} {quote_plus(secret)}")

    client = DartClient(api_key=secret, transport=transport, max_retries=1, retry_backoff=0)
    with pytest.raises(DartError) as error:
        request(client)
    rendered = "".join(traceback.format_exception(error.value)) + repr(client.diagnostics)
    for representation in (secret, quote(secret, safe=""), quote_plus(secret)):
        assert representation not in rendered
    assert client.request_count == 2
    assert client.diagnostics["retry_count"] == 1
    assert redact_api_key("url?crtfc_key=unknown&x=1") == "url?crtfc_key=[REDACTED]&x=1"


@pytest.mark.parametrize(
    "response", [(429, {}, b"secret"), (200, {}, b'{"status":"020","message":"secret"}')]
)
def test_listing_records_safe_blocked_rate_limit(response):
    client = DartClient(api_key="secret", transport=lambda *a, **k: response)
    result = list_annual_filings(client, corp_code="00126380", bgn_de="20250101", as_of="20251231")
    assert result["status"] == "blocked"
    assert result["reason"] == "rate_limited"
    assert result["coverage"] == "incomplete"
    assert result["request_count"] == 1
    assert len(result["raw_response_sha256"]) == 1
    assert "secret" not in json.dumps(result)
