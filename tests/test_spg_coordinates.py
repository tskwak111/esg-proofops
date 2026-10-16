"""SPG W19 warming remains source-, tenant- and lease-bound."""

import json

import pytest
from proofops_api import spg_coordinates
from proofops_api import w18_source_view as w19

from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import settings  # noqa: F401


def test_warm_pages_match_cold_inventory_and_still_hash_original(settings, monkeypatch):  # noqa: F811
    store, _, job = job_setup(settings)
    with store.transaction(readonly=True) as db:
        doc = dict(store._document(db, job["tenant_id"], job["document_id"]))
    pages = set(json.loads(job["pages"]))
    w19._cache.clear()
    expected, _ = w19._inventories(store, job, doc, pages)
    directory = store.document_dir(job["tenant_id"], job["document_id"])
    for file in (directory / "w19-inventory").glob("*.json"):
        file.unlink()
    w19._cache.clear()
    spg_coordinates.warm(store, job, settings.root)
    assert len(list((directory / "w19-inventory").glob("*.json"))) == len(pages)
    w19._cache.clear()
    assert w19._inventories(store, job, doc, pages)[0] == expected
    (directory / "original.pdf").chmod(0o600)
    (directory / "original.pdf").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="original_integrity"):
        w19._inventories(store, job, doc, pages)


@pytest.mark.parametrize("mutation", ["lease", "source", "tenant", "during_warm"])
def test_changed_authority_cannot_install_coordinates(settings, monkeypatch, mutation):  # noqa: F811
    store, _, job = job_setup(settings)
    directory = store.document_dir(job["tenant_id"], job["document_id"])

    def replace_lease():
        with store.transaction() as db:
            db.execute("UPDATE runs SET fence=fence+1 WHERE run_id=?", (job["run_id"],))

    if mutation == "lease":
        replace_lease()
    elif mutation == "source":
        (directory / "original.pdf").chmod(0o600)
        (directory / "original.pdf").write_bytes(b"tampered")
    elif mutation == "tenant":
        job = job | {"tenant_id": "foreign"}
    else:
        original = w19._inventories

        def raced(*args, **kwargs):
            result = original(*args, **kwargs)
            replace_lease()
            return result

        monkeypatch.setattr(w19, "_inventories", raced)
    spg_coordinates.warm(store, job, settings.root)
    assert not list((directory / "w19-inventory").glob("*.json"))
