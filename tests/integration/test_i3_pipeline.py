"""New v3 runs and resume retain every integrated option and exact source pin."""

import json
import os
import sqlite3
import sys

import pytest
from proofops.application.analysis_profile import (
    FINALS_H1_POLICY,
    FINALS_I3_POLICY,
    FINALS_I5_POLICY,
)
from proofops.domain.provenance import canonical_hash


@pytest.mark.parametrize(
    "policy,reader,h1",
    [
        (FINALS_I3_POLICY, "upstage-ocr-page-v11", False),
        (FINALS_H1_POLICY, "upstage-ocr-page-v12", True),
        (FINALS_I5_POLICY, "upstage-ocr-page-v12", True),
    ],
)
def test_i3_free_create_and_resume(tmp_path, monkeypatch, policy, reader, h1):
    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            "finals-unattended-v2",
            "--analysis-policy-sha256",
            canonical_hash(policy),
            "--pages",
            "1",
            "--claim-pages",
            "1",
            "--mixed-ocr-max-pages",
            "1",
        ],
    )
    assert pilot.main() == 0
    state = tmp_path / "state"
    settings = json.loads((state / "settings.json").read_text())
    for name in ("j3", "j7", "j8", "i3_wire", "k1", "k3"):
        assert settings["extraction_" + name] is True
    assert settings["claim_source_policy"]["profile"] == reader
    assert settings.get("extraction_h1", False) is h1
    assert settings.get("extraction_i4_identity", False) is bool(
        policy.get("extraction_selection_ids")
    )
    config = json.loads((state / "parser.json").read_text())
    assert config.get("local_resource_policy") == ("selected-pdf-h1-v1" if h1 else None)
    with sqlite3.connect(state / "state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["analysis_profile_policy"] == policy
    assert snapshot["analysis_profile_policy_sha256"] == canonical_hash(policy)
    before = {p: p.read_bytes() for p in (state / "settings.json", state / "pilot.json")}
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert all(p.read_bytes() == raw for p, raw in before.items())
