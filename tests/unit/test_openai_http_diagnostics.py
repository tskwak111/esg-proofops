"""Error evidence is private and immutable; an HTTP denial never triggers retry."""

import hashlib
import json
import stat

import pytest
from proofops.adapters.local import openai
from proofops.domain.provenance import canonical_hash


@pytest.mark.parametrize(
    "raw",
    [
        b'{"error":{"code":"permission_denied","type":"invalid_request_error",'
        b'"message":"private report and sk-private-key","param":"secret param"}}',
        b"<html>private report and sk-private-key</html>",
        b'{"error":["sk-private-key"]}',
    ],
)
def test_denial_preserves_safe_evidence_and_uncertain_budget(tmp_path, monkeypatch, raw):
    calls = []

    class Connection:
        status = 403

        def __init__(self, host, timeout):
            assert host == "api.openai.com"

        def request(self, method, path, **kwargs):
            calls.append(kwargs)

        def getresponse(self):
            return self

        def getheader(self, name):
            return {
                "x-request-id": "req_a123",
                "retry-after": "5",
                "set-cookie": "sk-private-key",
            }.get(name)

        def read(self, limit):
            return raw

        def close(self):
            pass

    monkeypatch.setattr(openai.http.client, "HTTPSConnection", Connection)
    probe = openai.OpenAIProbe("sk-private-key", tmp_path / "budget.sqlite3")
    with pytest.raises(ValueError, match="^OPENAI_HTTP_403$"):
        probe.complete("Return JSON", "{}", request_id="local-one", json_mode=True)
    assert len(calls) == 1
    assert probe.summary()["committed_usd"] == "0.02"
    assert probe.summary()["unsettled_calls"] == 1
    files = list(probe._responses.glob("*.http-error.json"))
    assert len(files) == 1
    text = files[0].read_text()
    evidence = json.loads(text)
    assert "private" not in text and "secret" not in text and "cookie" not in text
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert evidence["http_status"] == 403
    assert evidence["http_request_id"] == "req_a123"
    assert evidence["retry_after"] == "5"
    assert evidence["response_body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert evidence["request_sha256"] == canonical_hash(json.loads(calls[0]["body"]))
    assert evidence["diagnostic_policy_sha256"] == canonical_hash(openai.HTTP_ERROR_POLICY)
    assert evidence["error_code"] == (
        "permission_denied" if raw.startswith(b'{"error":{') else None
    )
    # Sidecar is not a success receipt and an acknowledged request cannot resend.
    with pytest.raises(ValueError, match="DUPLICATE_PROBE_REQUEST"):
        probe.complete("JSON", "{}", request_id="local-one")
    assert len(calls) == 1


def test_diagnostic_rejects_secret_identifiers_and_duplicate_rewrite(tmp_path):
    probe = openai.OpenAIProbe("sk-private-key", tmp_path / "budget.sqlite3")
    data = dict(error=dict(code="sk-private-key", type="sk-private-key"))
    raw = json.dumps(data).encode()
    probe._record_http_error({}, 403, raw, data["error"], "sk-private-key", "sk-private-key")
    path = next(probe._responses.glob("*.http-error.json"))
    original = path.read_bytes()
    probe._record_http_error({}, 403, raw, data["error"], "sk-private-key", "sk-private-key")
    assert path.read_bytes() == original
    assert b"sk-private-key" not in original
