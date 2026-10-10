"""DB1: all-claim scopes must not dispatch EV1 with an empty page selection."""

import json
import sys

import pytest
from proofops.adapters.local.run_store import LocalSQLiteRunStore

from evaluation.hosted_r108 import prepare_argv
from tests.test_hosted_analysis import source_pdf


@pytest.mark.parametrize("profile", ["finals-unattended-v1", "finals-unattended-v2"])
@pytest.mark.parametrize("claims", [[10], [10, 20]])
def test_ev1_policy_is_pinned_only_for_nonempty_evidence_scope(
    tmp_path, monkeypatch, profile, claims
):
    # Deployment-kit symlinks are outside the image's source scan. This fixture
    # isolates run-scope behavior; the actual image still runs its build gate.
    from proofops.application.supply_chain import SupplyChainResult

    from evaluation import local_upstage_pilot as pilot

    monkeypatch.setattr(
        "proofops_api.local_runtime.verify_supply_chain", lambda **_: SupplyChainResult(True)
    )
    __import__("pypdfium2")
    monkeypatch.setattr(sys, "platform", "linux")
    source = tmp_path / "selected.pdf"
    source.write_bytes(source_pdf())
    state = tmp_path / "state"
    config = dict(
        analysis_profile=profile,
        report_year=2024,
        period_start="2024-01-01",
        period_end="2024-12-31",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        prepare_argv(
            source,
            state,
            "11111111-1111-4111-8111-111111111111",
            config,
            dict(pages=[10, 20], claim_pages=claims, pipeline_profile=profile),
        ),
    )
    assert pilot.main() == 0
    manifest = json.loads((state / "pilot.json").read_text())
    snapshot = LocalSQLiteRunStore(state / "state.sqlite3").snapshot(
        manifest["tenant_id"], manifest["run_id"]
    )
    assert snapshot["claim_source_policy"]["profile"] == (
        "upstage-ocr-page-v9" if profile == "finals-unattended-v2" else "upstage-ocr-page-v5"
    )
    assert snapshot["parser_profile"]["claim_physical_pages"] == ([1] if claims == [10] else [1, 2])
    if claims == [10]:
        assert snapshot["evidence_source_policy"]["profile"] == "evidence-source-ocr-v1"
    else:
        assert "evidence_source_policy" not in snapshot


def test_remote_caddy_validation_cannot_consume_restart_command():
    """Model Docker's interactive stdin inside the SSH bash -s transport."""
    import subprocess
    from pathlib import Path

    script = (Path(__file__).parents[1] / "deploy/ec2/deploy.sh").read_text()
    validation = next(line for line in script.splitlines() if "caddy validate --config" in line)
    remote = (
        'sudo() { if [ "$1" = docker ]; then cat >/dev/null; '
        'elif [ "$1" = systemctl ]; then echo restarted; fi; }\n'
        + validation
        + "\nsudo systemctl restart proofops.service\n"
    )
    result = subprocess.run(
        ["bash", "-s"], input=remote, text=True, capture_output=True, check=True
    )
    assert result.stdout.strip() == "restarted", "interactive Caddy swallowed the restart command"
