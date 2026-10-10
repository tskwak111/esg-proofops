"""Company identity is operator-confirmed, tenant-bound and append-only."""

import json
import sqlite3
from unittest.mock import patch

import pytest
from proofops.adapters.local.reconciliation_store import (
    LocalReconciliationStore,
    ReconciliationRejected,
)
from proofops.application.registry import Registry

from tests.acceptance.test_upload import FOREIGN, TENANT
from tests.reconciliation.test_product_store import auth, fresh_store


@pytest.fixture
def setup(tmp_path):
    runs, store = fresh_store(tmp_path)
    registry = Registry.empty()
    company = registry.create_company(actor="owner", tenant_id=TENANT, legal_name="Example")
    return runs, store, registry, company


def test_link_is_audited_idempotent_and_immutable(setup):
    runs, store, registry, company = setup
    first = store.link_company(
        auth(),
        company.company_id,
        "00106641",
        registry=registry,
        reason="Operator checked DART legal identity",
    )
    assert (
        store.link_company(
            auth(), company.company_id, "00106641", registry=registry, reason="Repeated"
        )
        == first
    )
    assert store.company_link(auth("viewer"), company.company_id) == first
    with runs.jobs._transaction() as db:
        rows = db.execute("SELECT payload FROM reconciliation_company_link_audit").fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0][0])["created_by"] == "user-admin"
        for table in ("reconciliation_company_link", "reconciliation_company_link_audit"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(f"DELETE FROM {table}")
    with pytest.raises(ReconciliationRejected, match="COMPANY_LINK_CONFLICT"):
        store.link_company(auth(), company.company_id, "00126380", registry=registry, reason="x")


@pytest.mark.parametrize("code", ["", "123", "123456789", "１２３４５６７８", 106641, "0010664x"])
def test_invalid_codes_are_rejected(setup, code):
    _, store, registry, company = setup
    with pytest.raises(ReconciliationRejected, match="INVALID_DART_CORP_CODE"):
        store.link_company(auth(), company.company_id, code, registry=registry, reason="x")


def test_authority_and_tenant_isolation(setup):
    _, store, registry, company = setup
    with pytest.raises(ReconciliationRejected, match="FORBIDDEN"):
        store.link_company(
            auth("editor"), company.company_id, "00106641", registry=registry, reason="x"
        )
    with pytest.raises(ReconciliationRejected, match="RESOURCE_NOT_FOUND"):
        store.link_company(
            auth(tenant=FOREIGN), company.company_id, "00106641", registry=registry, reason="x"
        )
    with pytest.raises(ReconciliationRejected, match="unresolved_company_identity"):
        store.company_link(auth(), company.company_id)
    store.link_company(auth(), company.company_id, "00106641", registry=registry, reason="x")
    with pytest.raises(ReconciliationRejected, match="unresolved_company_identity"):
        store.company_link(auth(tenant=FOREIGN), company.company_id)


def test_v1_migration_preserves_old_rows_and_rolls_back_atomically(tmp_path):
    runs, _ = fresh_store(tmp_path)
    with runs.jobs._transaction() as db:
        db.execute("DROP TABLE reconciliation_company_link")
        db.execute("DROP TABLE reconciliation_company_link_audit")
        db.execute("UPDATE reconciliation_schema SET version=1")
        db.execute(
            "INSERT INTO reconciliation_revision VALUES (?,?,?,?,?,?,?,?)",
            (TENANT, "old", 1, "registration", "original", "2026-01-01", b"{}", "old-hash"),
        )
    # Simulate failure after DDL to verify the caller transaction restores v1.
    with pytest.raises(RuntimeError), runs.jobs._transaction() as db:
        LocalReconciliationStore._initialize(db)
        raise RuntimeError("interrupted migration")
    with runs.jobs._transaction() as db:
        assert db.execute("SELECT version FROM reconciliation_schema").fetchall() == [(1,)]
        assert (
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='reconciliation_company_link'"
            ).fetchone()
            is None
        )
        LocalReconciliationStore._initialize(db)
        assert db.execute("SELECT version FROM reconciliation_schema").fetchall() == [(2,)]
        assert db.execute("SELECT payload FROM reconciliation_revision").fetchone()[0] == b"{}"


def test_cli_uses_persisted_registry(tmp_path, capsys):
    from evaluation.reconciliation_link_company import main

    database = tmp_path / "server.sqlite3"
    registry = Registry.sqlite(database)
    company = registry.create_company(actor="owner", tenant_id=TENANT, legal_name="Example")
    registry.close()
    with patch.dict("os.environ", {"APP_ENV": "local"}):
        assert (
            main(
                [
                    "--database",
                    str(database),
                    "--tenant-id",
                    TENANT,
                    "--company-id",
                    company.company_id,
                    "--corp-code",
                    "00106641",
                    "--actor",
                    "operator",
                    "--reason",
                    "Checked original registry",
                ]
            )
            == 0
        )
    assert json.loads(capsys.readouterr().out)["corp_code"] == "00106641"
