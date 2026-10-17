"""Batching preserves the actual search output and every durable artifact byte."""

from proofops.adapters.local.spg_search_projection import Projection

from tests.acceptance.test_upload import TENANT
from tests.integration.test_local_tag_runner import verified_setup


def test_search_results_and_artifacts_are_byte_identical(tmp_path, monkeypatch):
    _, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    _, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    claim = discovery.claims[0]
    tracks = ("goal", "performance", "management")

    def read():
        return [
            runner.claims.missing_evidence(
                TENANT, run_id, claim, track=track, elements=[], original_graph=graph
            )
            for track in tracks
        ]

    expected = read()
    jobs = runner.claims.store.jobs
    query = (
        "SELECT kind,record_id,value FROM job_records "
        "WHERE kind IN ('document_evidence_search','element_evidence_search') "
        "ORDER BY kind,record_id"
    )
    with jobs._transaction() as db:
        before = db.execute(query).fetchall()
        db.execute(
            "DELETE FROM job_records "
            "WHERE kind IN ('document_evidence_search','element_evidence_search')"
        )
    projection = Projection(
        runner.claims, TENANT, run_id, graph, runner.claims.store.snapshot(TENANT, run_id)
    )
    runner.claims._spg_projection = projection
    assert read() == expected
    with jobs._transaction() as db:
        assert db.execute(query).fetchall() == []
    projection.finish()
    with jobs._transaction() as db:
        assert db.execute(query).fetchall() == before
