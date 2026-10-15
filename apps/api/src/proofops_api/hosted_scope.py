"""Free AS1 inspection in a resource-bounded child, no provider transport."""

import json
import os
import resource
import sys
from pathlib import Path


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    from proofops.application.analysis_profile import V2_PROFILE, policy_for

    from evaluation.hosted_scope_plan import inspect_streaming
    from evaluation.rb2_reporting_period import configured_profile

    pdf = Path(sys.argv[1])
    source_sha = sys.argv[3] if len(sys.argv) > 3 else None
    policy = policy_for(V2_PROFILE)
    reader = None

    def discovery(page):
        nonlocal reader
        if reader is None:
            from evaluation.scope_discovery_ocr import CPUDiscoveryReader

            reader = CPUDiscoveryReader(
                pdf,
                tenant_id=sys.argv[4],
                cache_dir=Path(sys.argv[2]).parent / "discovery-cache",
                source_sha256=source_sha,
            )
        return reader(page)

    plan = inspect_streaming(
        pdf,
        source_sha256=source_sha,
        scope_profile=policy.get("scope_profile"),
        ranking_policy=policy.get("scope_ranking")
        if policy.get("scope_ranking") == "W5-v1"
        else "W4-v2",
        discovery_reader=discovery if len(sys.argv) > 4 else None,
        reporting_period_policy=configured_profile(os.environ.get("HOSTED_LIVE_CONFIG")),
    )
    plan["source_path"] = "original.pdf"
    # Path is private operational metadata; hash the sanitized proposal actually stored.
    from proofops.domain.provenance import canonical_hash

    plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    Path(sys.argv[2]).write_text(json.dumps(plan, ensure_ascii=False))


def scope_selection(plan, source_sha256, page_count, *, reporting_scope=None, **kwargs):
    """Keep AS1 immutable proposal checks; bind the effective period to selection."""
    from proofops.domain.provenance import canonical_hash

    from evaluation.report_scope import validate_selection
    from evaluation.reporting_period import validate_period

    selection = validate_selection(plan, source_sha256, page_count, **kwargs)
    if reporting_scope is not None:
        if reporting_scope.get("report_year") is not None:
            validate_period(reporting_scope)
        selection["reporting_scope"] = reporting_scope
        selection["selection_sha256"] = canonical_hash(
            {k: v for k, v in selection.items() if k != "selection_sha256"}
        )
    return selection


if __name__ == "__main__":
    main()
