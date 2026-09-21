"""CLI smoke test against a REAL stored/committed local run (not a synthetic triple).

Builds a genuine extraction-committed run through the same fixture the
extraction/parser integration tests use (extraction_setup -> LocalExtractRunner
.run_once), then invokes scripts/linkage_exchange_cli.py's build-packet
function directly against that run's real sqlite database path. Confirms:
missing --financial-context cleanly blocks (never fabricates), and a real
claim_id from the actual committed extraction is found (not a claim_not_found
false negative).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from tests.integration.test_local_extract_runner import extraction_setup
from tests.integration.test_local_parser_runner import TENANT

CLI_PATH = Path(__file__).resolve().parents[2] / "scripts/linkage_exchange_cli.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("linkage_exchange_cli", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_packet_against_real_committed_run_blocks_without_financial_context(
    tmp_path, monkeypatch, capsys
):
    import subprocess

    real_run = subprocess.run

    def safe_run(cmd, *a, **kw):
        if cmd and cmd[0] == "/bin/ps":
            return subprocess.CompletedProcess(cmd, 0, stdout=b"1024\n")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", safe_run)

    service, run_id, runner, _now, _ = extraction_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"

    from proofops.adapters.local.claim_store import LocalClaimStore

    claims = LocalClaimStore(service.store, service.uploads, runner.parser)
    discovery = claims.load(TENANT, run_id)
    assert discovery.claims, "fixture must produce at least one real claim"
    claim_id = discovery.claims[0].claim_id

    cli = _load_cli_module()
    args = argparse.Namespace(
        tenant_id=TENANT,
        run_id=run_id,
        claim_id=claim_id,
        item="C1",
        database_path=service.store.path,
        financial_context=None,
        period_start=None,
        period_end=None,
        sr_published_at=None,
        trusted_company_id=None,
        contract_dir=str(cli.CONTRACT_DIR_DEFAULT),
    )
    exit_code = cli._cmd_build_packet(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing_financial_context" in captured.out
    assert "blocked" in captured.out


def test_build_packet_cli_rejects_untrusted_company_id_override(
    tmp_path, monkeypatch, capsys
):
    import subprocess

    real_run = subprocess.run

    def safe_run(cmd, *a, **kw):
        if cmd and cmd[0] == "/bin/ps":
            return subprocess.CompletedProcess(cmd, 0, stdout=b"1024\n")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", safe_run)

    service, run_id, runner, _now, _ = extraction_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"

    from proofops.adapters.local.claim_store import LocalClaimStore

    claims = LocalClaimStore(service.store, service.uploads, runner.parser)
    discovery = claims.load(TENANT, run_id)
    claim_id = discovery.claims[0].claim_id

    cli = _load_cli_module()
    args = argparse.Namespace(
        tenant_id=TENANT,
        run_id=run_id,
        claim_id=claim_id,
        item="C1",
        database_path=service.store.path,
        financial_context=None,
        period_start=None,
        period_end=None,
        sr_published_at=None,
        trusted_company_id="untrusted-spoofed-company-id",
        contract_dir=str(cli.CONTRACT_DIR_DEFAULT),
    )
    exit_code = cli._cmd_build_packet(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "company_mismatch" in captured.out


def test_build_packet_cli_rejects_untrusted_caller_sr_published_at_override(
    tmp_path, monkeypatch, capsys
):
    """Tiny regression: CLI must not treat caller CLI date as trusted source, nor use created_at."""
    import subprocess

    real_run = subprocess.run

    def safe_run(cmd, *a, **kw):
        if cmd and cmd[0] == "/bin/ps":
            return subprocess.CompletedProcess(cmd, 0, stdout=b"1024\n")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", safe_run)

    service, run_id, runner, _now, _ = extraction_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"

    from proofops.adapters.local.claim_store import LocalClaimStore

    claims = LocalClaimStore(service.store, service.uploads, runner.parser)
    discovery = claims.load(TENANT, run_id)
    claim_id = discovery.claims[0].claim_id

    cli = _load_cli_module()
    args = argparse.Namespace(
        tenant_id=TENANT,
        run_id=run_id,
        claim_id=claim_id,
        item="C1",
        database_path=service.store.path,
        financial_context=None,
        period_start=None,
        period_end=None,
        sr_published_at="2025-06-30",
        trusted_company_id=None,
        financial_local_paths=None,
        contract_dir=str(cli.CONTRACT_DIR_DEFAULT),
    )
    exit_code = cli._cmd_build_packet(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "period_mismatch" in captured.out
    assert "not an approved trusted publication source" in captured.out
