"""Replay saved E17 LG / E16 Kakao and LGE through the real source-view projection.

The HTTP harness supplies saved publication rows instead of the live account DB.
It retains HostedReads' parser/checkpoint/geometry validation and W18's full source
binding and bounded PDFium child. It does not call analysis or model providers.
Use private local COPIES of the server's pilot.json, state.sqlite3 and
parser-prepared artifacts under DATA/hosted/NAME/analysis/RUN_ID; original PDFs
are copied from E16/inputs.json. Authentication is covered by the hosted tests.
"""

import argparse
import collections
import importlib.util
import json
import pathlib
import shutil
import sqlite3
import subprocess
import time
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from proofops_api import w18_source_view as w18
from proofops_api.hosted_reads import HostedReads
from proofops_api.hosted_source_view import project_source_view

parser = argparse.ArgumentParser(
    description="Offline W19 HTTP projection replay; no provider calls."
)
parser.add_argument(
    "--data",
    type=pathlib.Path,
    required=True,
    help="Private local copies of parser publication artifacts",
)
parser.add_argument("--perf", type=pathlib.Path, required=True, help="Saved E16/E17 result folder")
parser.add_argument("--output", type=pathlib.Path, required=True)
parser.add_argument("--baseline", default="c3a30420")
args = parser.parse_args()
ROOT = args.data.resolve()
PERF = args.perf.resolve()
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=True)
baseline = ROOT / "baseline_w18.py"
baseline.write_bytes(
    subprocess.check_output(
        ["git", "show", f"{args.baseline}:apps/api/src/proofops_api/w18_source_view.py"]
    )
)
spec = importlib.util.spec_from_file_location("baseline_w18", baseline)
if spec is None or spec.loader is None:
    raise ImportError("Cannot load the saved W18 baseline module")
old: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
old.__file__ = w18.__file__
inputs = json.loads((PERF / "E16/inputs.json").read_bytes())
metrics = {}
for event, name in [("E17", "lg"), ("E16", "kakao"), ("E16", "lge")]:
    result = json.loads((PERF / event / f"{name}.result.json").read_bytes())
    accepted = json.loads((PERF / event / f"{name}.accepted.json").read_bytes())
    run = accepted["run_id"]
    directory = ROOT / "hosted" / name
    path = directory / "analysis" / run
    assert (
        path / "state.sqlite3"
    ).is_file(), f"Missing authenticated parser publication for {name}"
    doc = result["w16_source_document"] | dict(expires=2000000000)
    if not (directory / "original.pdf").exists():
        shutil.copyfile(inputs[name]["pdf"], directory / "original.pdf")
    with sqlite3.connect((path / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(db.execute("select payload from run_snapshots limit 1").fetchone()[0])
    row = dict(
        tenant_id=snapshot["tenant_id"],
        run_id=run,
        document_id=doc["document_id"],
        prepared_sha256=snapshot["document"]["sha256"],
    )
    store = SimpleNamespace(root=ROOT / "hosted", document_dir=lambda *args: directory)
    reads = HostedReads(store)
    app = FastAPI()

    @app.get("/v1/runs/{run_id}/result")
    def get_result(run_id: str, w18: bool = False):
        assert run_id == run
        return project_source_view(reads, row, doc, result, w18=w18)

    client = TestClient(app)
    url = f"/v1/runs/{run}/result"
    plain = client.get(url).content
    versions = {}
    stats: dict[str, Any] = {}
    new_enrich = w18.enrich
    observed = json.loads((PERF / event / f"{name}.w18-result.json").read_bytes())
    observed_refs = [r for c in observed["claims"] for r in c["w16_source_view"]["refs"]]
    stats["saved_server"] = dict(
        event=event,
        references=len(observed_refs),
        reasons=dict(collections.Counter(r["w18_reason"] or "exact" for r in observed_refs)),
    )
    artifact_hashes = {
        p: sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file()
    }
    native_project = w18.project_native_bbox
    counter = [0]

    def counted(*args):
        counter[0] += 1
        return native_project(*args)

    old.project_native_bbox = counted
    w18.project_native_bbox = counted
    shutil.rmtree(directory / "w19-inventory", ignore_errors=True)
    for mode in ["baseline_cold", "baseline_unbounded", "w19_cold", "w19_memory", "w19_disk"]:
        if mode.startswith("baseline"):
            w18.enrich = old.enrich
            old.W18_TOTAL_SECONDS = 8 if mode.endswith("cold") else 120
        else:
            w18.enrich = new_enrich
            if mode in ["w19_cold", "w19_disk"]:
                w18._cache.clear()
        counter[0] = 0
        started = time.monotonic()
        response = client.get(url + "?w18=true")
        elapsed = time.monotonic() - started
        assert response.status_code == 200
        value = response.json()
        versions[mode] = value
        refs = {
            (c["claim_id"], r["ref_id"]): r
            for c in value["claims"]
            for r in c["w16_source_view"]["refs"]
        }
        stats[mode] = dict(
            seconds=round(elapsed, 6),
            projections=counter[0],
            references=len(refs),
            reasons=dict(collections.Counter(r["w18_reason"] or "exact" for r in refs.values())),
        )
        assert client.get(url).content == plain
        print(name, mode, stats[mode], flush=True)
    w18.enrich = new_enrich
    w18.project_native_bbox = native_project
    reference = {
        (c["claim_id"], r["ref_id"]): r
        for c in versions["baseline_unbounded"]["claims"]
        for r in c["w16_source_view"]["refs"]
    }
    for mode in ["w19_cold", "w19_memory", "w19_disk"]:
        compared = 0
        for c in versions[mode]["claims"]:
            for r in c["w16_source_view"]["refs"]:
                before = reference[c["claim_id"], r["ref_id"]]
                if r["w18_reason"] is None:
                    for key in ["w18_line_rects", "w18_cell_rects", "w18_coordinates"]:
                        assert r[key] == before[key], (name, mode, key)
                    compared += 1
        stats[mode]["coordinates_identical"] = compared
    assert versions["w19_cold"] == versions["w19_memory"] == versions["w19_disk"]
    stats["legacy_http_bytes_unchanged"] = True
    assert all(
        sha256(p.read_bytes()).hexdigest() == digest for p, digest in artifact_hashes.items()
    )
    stats["publication_bytes_unchanged"] = True
    assert stats["w19_cold"]["reasons"].get("coordinate_timeout", 0) == 0
    stats["disk_bytes"] = sum(
        p.stat().st_size for p in (directory / "w19-inventory").glob("*.json")
    )
    metrics[name] = stats
    (OUT / f"{name}.w19-result.json").write_text(
        json.dumps(versions["w19_cold"], ensure_ascii=False)
    )
    (OUT / f"{name}.metrics.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
(OUT / "W19-metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
