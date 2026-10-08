"""Preview highlights use replayed spans without promoting whole paragraphs."""

from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from proofops.application.evidence.span_citations import span_verified_graph
from proofops_api.routers import sources

from tests.acceptance.test_upload import TENANT
from tests.integration.test_local_parser_runner import runner_setup
from tests.integration.test_run_lifecycle import client


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("verified", "allowed"),
        ("candidate", "unavailable"),
        ("different_span", "unavailable"),
        ("different_bbox", "unavailable"),
        ("missing_bbox", "unavailable"),
        ("replay_failure", None),
        ("paragraph_verified", "allowed"),
        ("parse_conflict", "unavailable"),
    ],
)
def test_preview_replays_only_the_requested_verified_span(tmp_path, monkeypatch, mode, expected):
    service, run_id, runner, now, _ = runner_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    graph = runner.load_graph(tenant_id=TENANT, run_id=run_id)
    block = next(b for b in graph.blocks if b.raw_text == "1234 tCO2e")
    ref = replace(block.source_ref(), verification_state="verified")
    if mode == "candidate":
        ref = replace(ref, verification_state="candidate")
    elif mode == "different_bbox":
        ref = replace(ref, bbox=(0, 0, 1, 1))
    elif mode == "missing_bbox":
        ref = replace(ref, bbox=None, location_quality="unlocated")
    verified_graph = span_verified_graph(graph, (ref,), "a" * 64)
    discovery = SimpleNamespace(claims=())
    if mode == "paragraph_verified":
        # Historical fully verified paragraphs need no claim-span sidecar.
        verified_graph = replace(
            graph,
            blocks=tuple(
                replace(b, quality="verified") if b.source_id == block.source_id else b
                for b in graph.blocks
            ),
        )
        discovery = SimpleNamespace(claims=(SimpleNamespace(source_refs=(ref,)),))
    elif mode == "parse_conflict":
        verified_graph = replace(
            verified_graph,
            issues=graph.issues
            + (SimpleNamespace(kind="parse_conflict", state="open", source_ids=(ref.source_id,)),),
        )
    calls = []

    def replay(self, tenant, run):
        calls.append((tenant, run))
        if mode == "replay_failure":
            raise ValueError("CLAIM_SNAPSHOT_HASH_MISMATCH")
        return {}, discovery, verified_graph

    monkeypatch.setattr(sources.LocalClaimStore, "load_evidence", replay)
    monkeypatch.setattr(sources, "render_page_preview", lambda *args: (b"png", 600, 800))
    http, auth = client(service)
    http.app.include_router(
        sources.build_sources_router(
            service.store,
            service.uploads,
            runner.parser,
            auth,
            allowed_origin="https://testserver",
            clock=lambda: now[0],
        )
    )
    ticket = http.post(f"/v1/runs/{run_id}/sources/{block.source_id}/view").json()
    signed = parse_qs(urlsplit(ticket["url"]).query)["ticket"][0]
    params = dict(ticket=signed, preview="page", char_start=0, char_end=ref.char_end)
    if mode == "different_span":
        params["char_end"] -= 1
    response = http.get(ticket["url"], params=params)
    if expected is None:
        assert response.status_code == 409
        assert "X-Source-Highlight" not in response.headers
    else:
        assert response.status_code == 200
        assert response.headers["X-Source-Highlight"] == expected
    assert calls == [(TENANT, run_id)]
    assert block.source_ref().verification_state == "candidate"
    assert graph.to_dict() == runner.load_graph(tenant_id=TENANT, run_id=run_id).to_dict()

    # Old page tickets and an incomplete span do not assert claim verification.
    for extra in ({}, {"char_start": 0}):
        response = http.get(ticket["url"], params={"ticket": signed, "preview": "page", **extra})
        assert response.headers["X-Source-Highlight"] == "unavailable"
    assert len(calls) == 1
