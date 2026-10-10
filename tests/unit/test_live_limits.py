"""Cost controls use only fake HTTP transports; provider dispatch is forbidden."""

import importlib.util
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "api" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


claim, report = load("live-claim"), load("live-report")
import _limits as limits  # noqa: E402


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_LIMITS_DB", str(tmp_path / "limits.sqlite3"))
    monkeypatch.setenv("DEMO_ACCESS_CODE", "secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    for name in (
        "LIVE_DISABLED",
        "LIVE_DAILY_LUNA_USD",
        "LIVE_IP_PER_MINUTE",
        "LIVE_TOTAL_PER_MINUTE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(limits.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("network"))


def usage(monkeypatch, value):
    def transport(request, timeout):
        assert request.full_url == "https://openrouter.ai/api/v1/key"
        assert request.get_method() == "GET"
        assert timeout == 5
        return io.BytesIO(json.dumps({"data": {"usage_daily": value}}).encode())

    monkeypatch.setattr(limits.urllib.request, "urlopen", transport)


def invoke(module, *, access="secret"):
    def forbidden(*_):
        pytest.fail("paid provider dispatched")

    if module is claim:
        return claim.run_claim({"claim": "탄소 감축"}, access_code=access, call_model=forbidden)
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    stream = io.BytesIO()
    writer.write(stream)
    return report.run_report(
        stream.getvalue(), [1], access_code=access, parse=forbidden, model=forbidden
    )


@pytest.mark.parametrize("module", [claim, report])
def test_daily_limit_before_paid_providers(monkeypatch, module):
    usage(monkeypatch, 0.50)
    with pytest.raises(limits.LiveError) as error:
        invoke(module)
    assert (error.value.status, error.value.code) == (429, "DAILY_LIMIT")


@pytest.mark.parametrize("value", [None, True, -1, "0", float("nan"), float("inf"), {}, []])
def test_malformed_usage_fails_closed(monkeypatch, value):
    usage(monkeypatch, value)
    with pytest.raises(limits.LiveError) as error:
        limits.check_limits("ip")
    assert (error.value.status, error.value.code) == (503, "LIMIT_CHECK_UNAVAILABLE")


@pytest.mark.parametrize("module", [claim, report])
def test_lookup_failure_before_providers(monkeypatch, module):
    def fail(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(limits.urllib.request, "urlopen", fail)
    with pytest.raises(limits.LiveError) as error:
        invoke(module)
    assert (error.value.status, error.value.code) == (503, "LIMIT_CHECK_UNAVAILABLE")


@pytest.mark.parametrize("module", [claim, report])
def test_kill_switch_and_wrong_key(monkeypatch, module):
    monkeypatch.setenv("LIVE_DISABLED", "1")
    for access, status, code in [("wrong", 403, "ACCESS_DENIED"), ("secret", 503, "LIVE_DISABLED")]:
        with pytest.raises(limits.LiveError) as error:
            invoke(module, access=access)
        assert (error.value.status, error.value.code) == (status, code)


def test_rate_limits_and_expiry(monkeypatch):
    usage(monkeypatch, 0.0)
    monkeypatch.setattr(limits, "monotonic", lambda: 100)
    for _ in range(6):
        limits.check_limits("client, proxy")
    with pytest.raises(limits.LiveError) as error:
        limits.check_limits("client, other-proxy")
    assert error.value.code == "RATE_LIMITED"
    for i in range(14):
        limits.check_limits(str(i))
    with pytest.raises(limits.LiveError) as error:
        limits.check_limits("new-client")
    assert error.value.status == 429
    monkeypatch.setattr(limits, "monotonic", lambda: 160)
    limits.check_limits("client")
    limits.check_limits("other-client")


def test_overrides_and_invalid_configuration(monkeypatch):
    usage(monkeypatch, 0.75)
    monkeypatch.setenv("LIVE_DAILY_LUNA_USD", "1")
    monkeypatch.setenv("LIVE_IP_PER_MINUTE", "1")
    limits.check_limits("client")
    with pytest.raises(limits.LiveError) as error:
        limits.check_limits("client")
    assert error.value.code == "RATE_LIMITED"
    monkeypatch.setenv("LIVE_TOTAL_PER_MINUTE", "0")
    with pytest.raises(limits.LiveError) as error:
        limits.check_limits("other")
    assert error.value.code == "LIMIT_CHECK_UNAVAILABLE"


@pytest.mark.parametrize("module", [claim, report])
def test_rate_rejection_before_providers(monkeypatch, module):
    usage(monkeypatch, 0.0)
    for _ in range(6):
        limits.check_limits("")
    with pytest.raises(limits.LiveError) as error:
        invoke(module)
    assert (error.value.status, error.value.code) == (429, "RATE_LIMITED")


def test_rate_limit_is_shared_by_separately_loaded_process_modules(monkeypatch):
    usage(monkeypatch, 0.0)
    monkeypatch.setenv("LIVE_IP_PER_MINUTE", "1")
    limits.check_limits("client")
    other = load("_limits")
    with pytest.raises(other.LiveError) as error:
        other.check_limits("client")
    assert error.value.code == "RATE_LIMITED"


def test_vercel_requires_shared_store_before_paid_work(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("LIVE_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("LIVE_REDIS_REST_TOKEN", raising=False)
    with pytest.raises(limits.LiveError) as error:
        limits.check_limits("client")
    assert error.value.code == "LIMIT_CHECK_UNAVAILABLE"


@pytest.mark.parametrize("admitted,code", [(0, None), (1, "RATE_LIMITED"), (2, "DAILY_LIMIT")])
def test_shared_store_reserves_rate_and_cost_in_one_operation(monkeypatch, admitted, code):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("LIVE_REDIS_REST_URL", "https://quota.invalid")
    monkeypatch.setenv("LIVE_REDIS_REST_TOKEN", "test-token")
    monkeypatch.setattr(limits, "daily_usage", lambda: 0.0)

    def transport(request, timeout):
        command = json.loads(request.data)
        assert command[0] == "EVAL" and command[2] == 3
        assert "INCRBY" in command[1] and "ZCARD" in command[1]
        assert timeout == 3
        return io.BytesIO(json.dumps({"result": admitted}).encode())

    monkeypatch.setattr(limits.urllib.request, "urlopen", transport)
    if code:
        with pytest.raises(limits.LiveError) as error:
            limits.check_limits("client")
        assert error.value.code == code
    else:
        limits.check_limits("client")
