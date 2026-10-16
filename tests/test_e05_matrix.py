"""Safety and one-variable checks for the diagnostic-only matrix."""

import json

from evaluation.e05_transport_matrix import CAP, MAX_ATTEMPTS, RESERVE, Matrix, local_echo


def test_denial_k3_stops_and_retains_uncertain_reservations(tmp_path, monkeypatch):
    class Response:
        status = 403
        version = 11

        def read(self, _):
            return b""

        def getheader(self, _):
            return None

    class Connection:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    matrix = Matrix(tmp_path, [b"{}", b"{}"], live=True, key="never-log-this")
    for i in range(4):
        matrix.invoke("H0", 0, i)
    assert len(matrix.calls) == 3 and matrix.stopped
    assert matrix.reserved == RESERVE * 3
    assert all(c["accounting"] == "pending" for c in matrix.calls)
    assert len(list(tmp_path.glob("*.reservation.json"))) == 3
    assert RESERVE * MAX_ATTEMPTS <= CAP
    assert "never-log-this" not in json.dumps(matrix.calls)


def test_echo_proves_one_variable_and_actual_negotiation(tmp_path):
    with local_echo() as (url, context):
        matrix = Matrix(tmp_path, [b'{"same":true}', b'{"same":true}'], url=url, verify=context)
        for case in ("H0", "H1", "H2", "H3", "H5"):
            matrix.invoke(case, 0, 0)
        with matrix.client() as pool:
            matrix.invoke("H4", 0, 0, pool)
            matrix.invoke("H4", 0, 1, pool)
    calls = matrix.calls
    assert all(c["http_status"] == 200 for c in calls)
    assert len({c["echo"]["wire_sha256"] for c in calls}) == 1
    assert len({c["echo"]["authorization_sha256"] for c in calls}) == 1
    baseline = calls[0]["echo"]
    for call, field in ((calls[1], "accept"), (calls[2], "user-agent")):
        assert set(call["echo"]["header_names"]) - set(baseline["header_names"]) == {field}
        assert {k: v for k, v in call["echo"]["header_settings"].items() if k != field} == (
            baseline["header_settings"]
        )
    assert calls[3]["echo"]["header_names"] == baseline["header_names"]
    assert calls[3]["echo"]["header_settings"] == baseline["header_settings"]
    assert calls[4]["http_version"] == "HTTP/2"
    assert calls[-1]["connection_reused"]
    assert calls[-1]["echo"]["connection_id"] == calls[-2]["echo"]["connection_id"]
    assert sum(float(c["exposure_usd"]) for c in calls) == 0
