"""One bounded Hyundai product-path canary; A parsing reused, no table bypass."""

import hashlib
import itertools
import os
import sys
from pathlib import Path
from time import monotonic

from proofops.adapters.local.decisions import DecisionProbe
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.adapters.local.upstage import UpstageProbe
from proofops.adapters.local.upstage_parse import UpstageParseProbe
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, _json
from proofops.adapters.parsing.upstage_document import MODEL, selected_pdf
from proofops.domain.provenance import canonical_hash

from evaluation import local_upstage_pilot as pilot
from evaluation.h1_holdout import LAB, OUT, ROOT, A, funded_probe, load_a_scorer, read, write
from scripts.finals_demo import FinalsBudget, parse_bound


def main(
    *,
    workers=2,
    output_dir=None,
    probe_factory=funded_probe,
    budget_factory=FinalsBudget,
    input_state=None,
    selected_pages=(22, 41),
    claim_pages=None,
    cached_states=None,
):
    out = output_dir or OUT
    load_a_scorer()  # Make A's unchanged, narrow OCR bookkeeping helper available.
    from evaluation.a_funded_ocr import install

    _, openai_fence = probe_factory()
    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openai", "upstage", "openrouter")}
    upstage_fence = budget_factory(
        LAB / "sprint3/E2E/r108-spend.json",
        ledgers,
        out / "product-upstage-calls.jsonl",
        task="H1-upstage",
        limit_usd="0.5",
    )
    state = out / "product-hyundai"
    if state.exists():
        raise ValueError("H1_FRESH_PRODUCT_STATE_REQUIRED")
    UpstageParseProbe.parse_async = upstage_fence.guarded(
        UpstageParseProbe.parse_async, "upstage", parse_bound
    )

    def deny(*args, **kwargs):
        raise ValueError("H1_UNAUTHORIZED_PROVIDER")

    UpstageProbe._post = OpenRouterProbe._post = DecisionProbe._post = deny
    local = pilot.ROOT / ".local"
    local.mkdir(exist_ok=True)
    for provider in ledgers:
        link = local / provider
        if not link.exists():
            link.symlink_to(ROOT / ".local" / provider, target_is_directory=True)
        assert (link / "budget.sqlite3").samefile(ledgers[provider])
    os.environ.update(
        PROOFOPS_SPEND_LEDGER=str(out / "product-spend.sqlite3"),
        PROOFOPS_SPEND_GROUP="H1-product",
        PROOFOPS_SPEND_GROUP_LIMIT="1.7",
        PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT),
        LOCAL_LLM_MAX_WORKERS=str(workers),
        UPSTAGE_OCR_LEDGER=str(ledgers["upstage"]),
        R108_SPEND_PATH=str(LAB / "sprint3/E2E/r108-spend.json"),
    )
    original_read = Path.read_text

    def keys(path, *args, **kwargs):
        if path == pilot.ROOT / ".env.upstage.local":
            path = ROOT / path.name
        return original_read(path, *args, **kwargs)

    Path.read_text = keys
    manifest = read((input_state or A / "states/현대자동차-p22") / "pilot.json")
    caches = [
        path
        for cached in (cached_states or (A / "states/현대자동차-extraction-initial-failed",))
        for path in (cached / "parser-prepared/upstage-cache").rglob("*.json")
    ]
    original_parse = OpenDataLoaderParser.parse
    reused = []

    def cached_parse(parser, source, profile, *, tenant_id, **kwargs):
        if source.sha256 != manifest["source_sha256"]:
            raise ValueError("H1_SOURCE_SCOPE_INVALID")
        directory = parser.artifact_root / "upstage-cache" / tenant_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for cache in caches:
            collected = read(cache)
            for subset in itertools.combinations(selected_pages, collected["pages"]):
                pdf = selected_pdf(source.content, subset)
                body = dict(
                    model=MODEL,
                    mode=collected["mode"],
                    pdf_sha256=hashlib.sha256(pdf).hexdigest(),
                    pages=len(subset),
                    bytes_len=len(pdf),
                    transport="async",
                )
                key = hashlib.sha256(
                    _json(
                        dict(
                            source_sha256=source.sha256,
                            pages=subset,
                            model=MODEL,
                            mode=collected["mode"],
                        )
                    )
                ).hexdigest()
                if key != cache.stem:
                    continue
                assert canonical_hash(body) == collected["request_sha256"]
                assert canonical_hash(collected["raw_batches"]) == collected["response_sha256"]
                target = directory / (key + ".json")
                if not target.exists():
                    with target.open("xb") as stream:
                        stream.write(_json(collected))
                    target.chmod(0o400)
                    reused.append(key)
        return original_parse(parser, source, profile, tenant_id=tenant_id, **kwargs)

    OpenDataLoaderParser.parse = cached_parse
    restore = install(state, upstage_fence, ledgers["upstage"])
    sys.argv = [
        "pilot",
        "--pdf",
        manifest["source_path"],
        "--state",
        str(state),
        "--pages",
        ",".join(map(str, selected_pages)),
        "--claim-pages",
        ",".join(map(str, claim_pages or selected_pages)),
        "--report-year",
        str(manifest.get("report_year", 2025)),
        "--period-start",
        "2024-01-01",
        "--period-end",
        "2024-12-31",
        "--analysis-profile",
        "finals-unattended-v2",
        "--max-calls",
        "256",
        "--extraction-total-calls",
        "400",
        "--tagging-max-calls",
        "1800",
        "--parser-max-output-bytes",
        "134217728",
        "--parser-memory-bytes",
        "805306368",
        "--key-file",
        str(ROOT / ".env.openai.local"),
        "--ai-project-review",
        "--invoke",
    ]
    write(out / "product-argv.json", sys.argv)
    started, code = monotonic(), None
    try:
        code = pilot.main()
    finally:
        restore()
        Path.read_text = original_read
        OpenDataLoaderParser.parse = original_parse
        result = dict(
            exit_code=code,
            seconds=round(monotonic() - started, 3),
            parsing_reused=reused,
            grid_bypass=False,
            product_profile=read(state / "pilot.json").get("analysis_policy_sha256"),
        )
        for provider, fence in (("openai", openai_fence), ("upstage", upstage_fence)):
            with fence.transaction() as (_, entry):
                result[provider] = dict(
                    task_usd=entry["delta_usd"], reserved_usd=entry["reserved_usd"]
                )
        write(out / "product-summary.json", result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
