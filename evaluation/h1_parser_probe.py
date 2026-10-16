"""Paid-call-free reproduction on Hyundai's actual original PDF."""

import argparse
import json
import os
import platform
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import uuid4

from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact

from evaluation.h1_holdout import OUT, A, write
from evaluation.pa9_source_gate import fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--resource-policy")
    args = parser.parse_args()
    graph, content, _, snapshot, _ = fixture(A / "states/현대자동차-p22")
    doc = snapshot["document"]
    source = SourceArtifact(
        graph.tenant_id,
        doc["document_id"],
        doc["version_id"],
        graph.source_sha256,
        doc["object_version_id"],
        content,
        upload_security_limits=doc["upload_security"]["limits"],
    )
    extras = {"local_resource_policy": args.resource_policy} if args.resource_policy else {}
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=(22, 41),
        java_executable=os.environ.get(
            "PROOFOPS_TEST_JAVA", "/opt/homebrew/opt/openjdk@21/bin/java"
        ),
        timeout_seconds=120,
        memory_bytes=768 * 1024 * 1024,
        max_output_bytes=134217728,
        table_structure_repair="odl_header_v2",
        **extras,
    )
    target = OUT / "parser" / args.label
    started = monotonic()
    cgroup = Path("/sys/fs/cgroup/memory.max")
    result = dict(
        profile=profile.invocation_snapshot(),
        source_sha256=sha256(content).hexdigest(),
        remote_calls=0,
        actual_host=platform.system(),
        enforced_host_memory_bytes=cgroup.read_text().strip() if cgroup.exists() else None,
    )
    try:
        adapter = OpenDataLoaderParser(target)
        result_graph = adapter.parse(source, profile, tenant_id=graph.tenant_id)
        assert adapter.load_verified(source, profile, tenant_id=graph.tenant_id) == result_graph
        result.update(
            status="completed",
            pages=sorted({b.page_num for b in result_graph.blocks}),
            blocks=len(result_graph.blocks),
            replay_identical=True,
        )
    except ParseFailure as error:
        result.update(status="failed", code=str(error), stderr_artifact=str(error.stderr_path))
    result["seconds"] = round(monotonic() - started, 3)
    write(target / "result.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
