"""HTTP health/login/CSRF/upload/202/poll/result/purge probe. No credentials in output."""

import argparse
import json
import os
import stat
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


def smoke_pdf():
    """Small readable environment page so automatic scope planning can succeed."""
    paragraph = (
        "During the reporting year, greenhouse gas emissions fell through energy efficiency. "
        "The environment program tracks climate impacts, carbon emissions, renewable energy, "
        "water use, and waste across company operations. This disclosure describes the method "
        "used to measure environmental performance and the boundary for reported emissions."
    )
    escaped = paragraph.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = (
        "BT\n/F1 18 Tf\n72 720 Td\n(Environment) Tj\n" f"/F1 10 Tf\n0 -30 Td\n({escaped}) Tj\nET\n"
    ).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica " b"/Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets[1:])
    return (
        pdf
        + f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base", required=True, help="https://production-domain/hosted-api or local HTTP loopback"
    )
    p.add_argument("--origin", required=True)
    p.add_argument("--invite-file", required=True, type=Path)
    p.add_argument("--foreign-invite-file", required=True, type=Path)
    p.add_argument(
        "--expect", choices=["blocked", "result", "linux-blocked-result"], default="blocked"
    )
    p.add_argument(
        "--allow-live",
        action="store_true",
        help="Explicitly allow a paid run for a later approved reader release",
    )
    p.add_argument("--pdf", type=Path, help="Optional authorized upload fixture; never echoed")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    assert args.base.startswith("https://") or args.base.startswith(
        "http://127.0.0.1:"
    ), "HTTPS or loopback required"
    for invite_file in (args.invite_file, args.foreign_invite_file):
        assert (
            stat.S_IMODE(invite_file.stat().st_mode) == 0o600 and not invite_file.is_symlink()
        ), "0600 invite file required"
    cookie = None
    csrf = None
    document = None
    report = {}
    started = time.monotonic()

    def request(
        path,
        method="GET",
        body=None,
        headers=None,
        *,
        session_cookie=None,
        session_csrf=None,
    ):
        h = {"Origin": args.origin} | (headers or {})
        selected_cookie = cookie if session_cookie is None else session_cookie
        selected_csrf = csrf if session_csrf is None else session_csrf
        if selected_cookie:
            h["Cookie"] = selected_cookie
        if selected_csrf:
            h["X-CSRF-Token"] = selected_csrf
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(
            args.base.rstrip("/") + path, method=method, data=body, headers=h
        )
        before = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                status = r.status
                rh = r.headers
        except urllib.error.HTTPError as e:
            data = e.read()
            status = e.code
            rh = e.headers
        elapsed = round(time.monotonic() - before, 3)
        try:
            payload = json.loads(data) if data else {}
        except ValueError:
            raise AssertionError(f"Non-JSON response: HTTP {status}") from None
        return status, payload, rh, elapsed

    try:
        status, health, _, _ = request("/v1/health/live")
        assert status == 200 and health["status"] == "ok"
        status, ready, _, _ = request("/v1/health/ready")
        assert status == 200 and ready["control_plane"]
        status, runtime, _, _ = request("/v1/runtime")
        assert status == 200
        # P3 key-free runtime must remain unable to dispatch providers.
        if args.expect == "linux-blocked-result":
            assert (
                runtime["live_analysis"] is False and runtime["source_verifier"] == "unresolved"
            ), "Linux source gate required"
        elif not args.allow_live:
            assert (
                runtime["live_disabled"] is True
            ), "Paid transport enabled: abort before upload/run"
        status, session, h, _ = request(
            "/v1/auth/invitation", "POST", {"code": args.invite_file.read_text().strip()}
        )
        assert status == 200, f"Login HTTP {status}"
        set_cookie = h.get("Set-Cookie", "")
        assert (
            "__Host-proofops_session=" in set_cookie
            and "Secure" in set_cookie
            and "HttpOnly" in set_cookie
            and "samesite=lax" in set_cookie.lower()
            and "Path=/" in set_cookie
            and "domain=" not in set_cookie.lower()
        )
        cookie = set_cookie.split(";", 1)[0]
        csrf = session["csrf_token"]
        assert request("/v1/session")[0] == 200
        report.update(
            health=200, login=200, cookie_attributes="Secure/HttpOnly/Path=/SameSite=Lax/no Domain"
        )
        pdf = args.pdf.read_bytes() if args.pdf else smoke_pdf()
        status, doc, _, elapsed = request(
            "/v1/documents",
            "POST",
            pdf,
            {"Content-Type": "application/pdf", "Idempotency-Key": str(uuid4())},
        )
        assert status == 201, f"Upload HTTP {status}"
        document = doc["document_id"]
        report.update(upload=201, upload_bytes=len(pdf), upload_seconds=elapsed)

        scope_url = f"/v1/documents/{document}/scope-plan"
        status, created_scope, scope_headers, elapsed = request(scope_url, "POST")
        assert status == 200, f"Scope plan HTTP {status}"
        assert created_scope["plan"]["status"] == "candidate_only" and created_scope["selection"]
        revision = created_scope["revision"]
        etag = f'"{revision}"'
        assert scope_headers.get("ETag") == etag

        # Confirm the persisted proposal and verify missing If-Match is rejected
        # without creating a new selection revision.
        status, scope, read_headers, _ = request(scope_url)
        assert status == 200 and read_headers.get("ETag") == etag
        assert scope["plan"]["plan_sha256"] == created_scope["plan"]["plan_sha256"]
        assert (
            scope["selection"]["selection_sha256"] == created_scope["selection"]["selection_sha256"]
        )
        selection = scope["selection"]
        status, _, _, _ = request(
            scope_url + "/selection",
            "POST",
            {
                "selected_claim_pages": selection["claim_pages"],
                "selected_evidence_pages": selection["pages"],
            },
        )
        assert status == 428, f"Scope selection without If-Match HTTP {status}"
        status, confirmed_scope, confirmed_headers, _ = request(scope_url)
        assert status == 200 and confirmed_headers.get("ETag") == etag
        assert confirmed_scope["selection"]["selection_sha256"] == selection["selection_sha256"]
        report.update(
            scope_plan="candidate_only",
            scope_revision=revision,
            scope_confirmation="GET matches POST",
            scope_if_match_guard=428,
            scope_edits=0,
            scope_seconds=elapsed,
        )

        status, run, _, elapsed = request(
            "/v1/runs",
            "POST",
            {
                "document_id": document,
                "scope_selection_sha256": selection["selection_sha256"],
            },
            {"Idempotency-Key": str(uuid4())},
        )
        assert status == 202, f"Run HTTP {status}"
        report.update(run=202, run_selection="unmodified scope hash", accept_seconds=elapsed)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            status, current, _, _ = request(run["status_url"])
            assert status == 200
            if current["status"] in ("completed", "partial_blocked", "failed", "cancelled"):
                break
            time.sleep(1)
        else:
            raise AssertionError("Worker polling deadline exceeded")
        assert current["status"] in (
            "completed",
            "partial_blocked",
        ), f"Worker terminal state: {current['status']}"
        status, result, _, _ = request("/v1/runs/" + run["run_id"] + "/result")
        if args.expect == "blocked":
            assert (
                current["status"] == "partial_blocked"
                and current["error_code"] == "LIVE_BINDING_UNAVAILABLE"
            )
            assert (
                status == 200
                and result["schema"] == "r108-hosted-result-v1"
                and result["hold_reasons"] == ["LIVE_BINDING_UNAVAILABLE"]
                and result["pipeline"]["status"] == "partial_blocked"
                and result["pipeline"]["provider_calls"] == 0
                and result["confirmed_grade"] is None
                and result["claims"] == []
            )
            report.update(
                poll="partial_blocked",
                result=200,
                reason="LIVE_BINDING_UNAVAILABLE",
                provider_calls=0,
            )
        else:
            assert status == 200 and result["schema"] == "r108-hosted-result-v1"
            report.update(
                poll=current["status"],
                result=200,
                claims=len(result["claims"]),
                hold_reasons=result["hold_reasons"],
                pipeline_profiles=result["pipeline"]["profiles"],
            )
            if args.expect == "linux-blocked-result":
                assert (
                    current["status"] == "partial_blocked"
                    and result["hold_reasons"] == ["LINUX_SOURCE_READER_UNRESOLVED"]
                    and result["confirmed_grade"] is None
                    and result["claims"] == []
                )
                report["provider_calls"] = 0
        status, foreign_session, foreign_headers, _ = request(
            "/v1/auth/invitation",
            "POST",
            {"code": args.foreign_invite_file.read_text().strip()},
            session_cookie="",
            session_csrf="",
        )
        assert status == 200, f"Foreign tenant login HTTP {status}"
        foreign_cookie = foreign_headers.get("Set-Cookie", "").split(";", 1)[0]
        assert foreign_cookie
        status, _, _, _ = request(
            f"/v1/documents/{document}",
            session_cookie=foreign_cookie,
            session_csrf=foreign_session["csrf_token"],
        )
        assert status == 404, f"Foreign tenant document HTTP {status}"
        report["tenant_isolation"] = 404
        assert (
            request(
                "/v1/auth/logout",
                "POST",
                session_cookie=foreign_cookie,
                session_csrf=foreign_session["csrf_token"],
            )[0]
            == 204
        )
    finally:
        if document and cookie and csrf:
            status, deletion, _, _ = request(
                "/v1/documents/" + document + "/deletion-requests",
                "POST",
                {"reason": "deployment smoke fixture cleanup"},
                {"Idempotency-Key": str(uuid4())},
            )
            assert (
                status == 202 and deletion["status"] == "completed"
            ), "Smoke purge incomplete; operator must retry maintenance"
            assert request("/v1/documents/" + document)[0] == 404
            report["purge"] = "completed"
            report["document_after_purge"] = 404
        if cookie and csrf:
            assert request("/v1/auth/logout", "POST")[0] == 204
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(output)
    print(output, end="")


if __name__ == "__main__":
    main()
