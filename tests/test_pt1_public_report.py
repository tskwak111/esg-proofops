"""Public opt-in: real PDF boundaries, injected transports, no paid calls."""

from tests.acceptance.test_parsing import pdf
from tests.test_live_report_handler import report


def test_public_unverified_claim_gets_provisional_not_confirmed(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_CODE", "PT1-test")
    monkeypatch.setattr(report, "check_limits", lambda *_: None)
    parsed = {
        "model": "document-parse-260128",
        "usage": {"standard": [1], "pages": 1},
        "elements": [
            {
                "page": 1,
                "category": "paragraph",
                "coordinates": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.2},
                    {"x": 0.1, "y": 0.2},
                ],
                "content": {"text": "Unverified environmental management statement."},
            },
        ],
    }
    requests = []

    def model(system, user, cap):
        requests.append(user)
        if "blocks" in user:
            return {
                "claims": [
                    {
                        "block": 0,
                        "quote": "Unverified environmental management statement.",
                        "track": "management",
                    }
                ]
            }, 0.0001
        return {
            "claims": [
                {
                    "index": 0,
                    "elements": [
                        {
                            "name": "named_means_or_concrete_state",
                            "state": "present",
                            "quote": "Unverified",
                        }
                    ],
                }
            ]
        }, 0.0001

    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf())).pages[0])
    stream = BytesIO()
    writer.write(stream)
    result = report.run_report(
        stream.getvalue(),
        [1],
        access_code="PT1-test",
        parse=lambda _: parsed,
        model=model,
        pipeline_profile="unattended-v1",
    )
    claim = result["claims"][0]
    assert len(requests) == 4 and [r["replicate_id"] for r in requests[1:]] == [1, 2, 3]
    assert claim["source_status"]["display"] == "원문 확인 필요"
    assert claim["decision"] is None
    assert claim["provisional_grade"]["decision_status"] == "provisional"
    assert all(e["state"] == "unknown" for e in claim["elements"])
    assert result["pipeline_status"] == "completed"
