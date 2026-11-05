"""Keep split modules independently importable and facade hooks effective."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_IMPORTS = (
    ("proofops_worker.extraction_parts.selection", "proofops_worker.extract_runner"),
    ("proofops_worker.extraction_parts.dispatch", "proofops_worker.extract_runner"),
    ("proofops_worker.extraction_parts.single_shot", "proofops_worker.extract_runner"),
    ("proofops.adapters.local.openai_http", "proofops.adapters.local.openai"),
    ("proofops.adapters.local.job_store_parser", "proofops.adapters.local.job_store"),
    ("proofops.adapters.local.job_store_checkpoint", "proofops.adapters.local.job_store"),
    ("proofops.adapters.local.job_store_actions", "proofops.adapters.local.job_store"),
    ("proofops.adapters.local.reviewed_table_layout", "proofops.adapters.local.reviewed_table"),
    (
        "proofops.adapters.local.reviewed_claim_sources",
        "proofops.adapters.local.reviewed_claim_bridge",
    ),
    ("proofops.application.report_rendering", "proofops.application.reporting"),
    (
        "proofops.application.tagging.preliminary_prompts",
        "proofops.application.tagging.preliminary",
    ),
    ("proofops.application.tagging.response_guard", "proofops.application.tagging.service"),
    *(
        (f"evaluation.local_upstage_pilot_{part}", "evaluation.local_upstage_pilot")
        for part in ("cli", "profiles", "resume", "runtime", "settings")
    ),
)


@pytest.mark.parametrize("module,facade", _IMPORTS)
@pytest.mark.parametrize("facade_first", (False, True), ids=("split-first", "facade-first"))
def test_split_module_imports_in_fresh_interpreter(module, facade, facade_first):
    modules = (facade, module) if facade_first else (module, facade)
    result = subprocess.run(
        [sys.executable, "-c", "; ".join(f"import {name}" for name in modules)],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("entrypoint", ("normalize_reviewed_layout", "artifact_from_review"))
def test_reviewed_table_graph_hook(monkeypatch, entrypoint):
    from proofops.adapters.local import reviewed_table as table

    calls = []

    def replacement(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("R2_GRAPH_HOOK")

    monkeypatch.setattr(table, "graph_from_review", replacement)
    with pytest.raises(RuntimeError, match="^R2_GRAPH_HOOK$"):
        getattr(table, entrypoint)({}, b"", tenant_id="tenant")
    assert calls == [(({}, b""), {"tenant_id": "tenant"})]
