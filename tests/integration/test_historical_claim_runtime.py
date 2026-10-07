"""The real runtime gate recognizes the saved policy, never an altered policy."""

import json
from pathlib import Path

import pytest
from proofops_api.local_runtime import load_local_runtime

from tests.integration.test_local_runtime_config import (
    _budget_limits,
    _parser_snapshot,
    _probe_extraction_profile,
    _write_json,
)


@pytest.mark.parametrize("tamper", [False, True])
def test_runtime_loads_only_exact_historical_claim_policy(tmp_path, tamper):
    policy = json.loads(
        Path("tests/fixtures/pipeline/claim-span-typography-history/policy.json").read_text()
    )
    if tamper:
        policy["wrapper_sha256"] = "0" * 64
    parser = _write_json(tmp_path / "parser.json", _parser_snapshot())
    settings = _write_json(
        tmp_path / "settings.json",
        {
            "build_root": str(tmp_path),
            "budget_limits": _budget_limits(),
            "extraction_profile": _probe_extraction_profile(),
            "extraction_limits": {"max_calls": 2, "max_output_tokens": 128},
            "claim_source_policy": policy,
        },
    )
    env = {
        "LOCAL_PARSER_PROFILE_PATH": str(parser),
        "LOCAL_RUN_SETTINGS_PATH": str(settings),
        "LOCAL_EXTRACTION_MODE": "upstage_probe",
    }
    if tamper:
        with pytest.raises(ValueError, match="LOCAL_RUNTIME_CONFIG_INVALID"):
            load_local_runtime(env)
    else:
        assert load_local_runtime(env)["claim_source_policy"] == policy
