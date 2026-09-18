"""One pinned real-PDF E/appendix case, with explicit offline tagging fixtures.

Run: uv run --no-sync python evaluation/e_scope_case.py --pdf PATH --output DIR --java PATH
No product model, cloud, source-quality approval or published decision is performed.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.claims import ClaimScope, ExtractionProfile, discover_atomic_claims
from proofops.application.evidence.retrieval import SearchHit, SearchResult, retrieve_evidence
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
from proofops.application.ingest.normalize import normalize_table_bindings, normalize_tables
from proofops.application.rulepacks import validate_rulepack
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import pack_content_hash, snapshot_from_validated
from proofops.domain.rules.engine import ConfirmedTags, RuleContext, evaluate

PDF_SHA256 = "c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde"
CLAIMS = (
    (
        "향후 생산능력 확대 및 글로벌 사업 확장에 따른 배출량 증가 요인에도 불구하고, "
        "Scope 1 및 Scope 2 배출량을 기준연도(2019년, 951만 tCO₂e) 수준으로 관리하는 "
        "탄소중립 성장(Carbon Neutral Growth)을 2030년 목표로 설정하고 있습니다."
    ),
    (
        "2025년에는 총 8건의 에너지 효율화 과제를 통해 약 3만 톤의 온실가스를 저감하였으며, "
        "주요 생산공정정에서 추진한 에너지 효율화 사례는 다음과 같습니다."
    ),
)


class OfflineClaimFixture:
    """Exact reviewed span candidates; unmatched text remains unknown."""

    def __init__(self, rule_hash):
        self.profile = ExtractionProfile(
            canonical_hash({"fixture": "e-scope-offline-v1"}),
            canonical_hash({"claims": CLAIMS}),
            rule_hash,
            synthetic=True,
        )

    def extract(self, packet):
        text = packet["untrusted_document_data"]["text"]
        return {
            "spans": [
                dict(
                    char_start=text.index(quote),
                    char_end=text.index(quote) + len(quote),
                    quote=quote,
                    kind="claim",
                    reason=None,
                    topic_ids=["environment"],
                )
                for quote in CLAIMS
                if quote in text
            ]
        }


class OfflineLexicalSearch:
    """Bounded lexical probe of selected appendix pages; no vector/model calls."""

    synthetic = True

    def __init__(self, graph):
        self.graph = graph

    def search(self, scope, query, *, vector=None):
        assert (scope.tenant_id, scope.document_version_id, scope.parse_manifest_id) == (
            self.graph.tenant_id,
            self.graph.document_version_id,
            self.graph.parse_manifest_id,
        )
        if vector is not None:
            return SearchResult(status="not_run")
        terms = set(re.findall(r"\w+", query.casefold()))
        candidates = [
            b for b in self.graph.blocks if b.page_num in (97, 117) and b.raw_text.strip()
        ]
        candidates.sort(
            key=lambda b: (
                -len(terms & set(re.findall(r"\w+", b.raw_text.casefold()))),
                b.source_id,
            )
        )
        return SearchResult(
            tuple(
                SearchHit(scope, b.source_id, sha256(b.raw_text.encode()).hexdigest())
                for b in candidates[:20]
            ),
            "bounded",
        )


def run(pdf: Path, output: Path, java: str):
    content = pdf.read_bytes()
    if sha256(content).hexdigest() != PDF_SHA256:
        raise ValueError("This case requires the pinned LG Chem PDF; no silent fixture reuse.")
    output.mkdir(parents=True, exist_ok=False)
    source = SourceArtifact(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        PDF_SHA256,
        "local-user-corpus:" + PDF_SHA256,
        content,
    )
    profile = ParserProfile(str(uuid4()), physical_pages=(24, 97, 117), java_executable=java)
    parser = OpenDataLoaderParser(output / "artifacts")
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    assert parser.load_verified(source, profile, tenant_id=source.tenant_id) == graph
    assert {b.page_num for b in graph.blocks} == {24, 97, 117}

    config = Path(__file__).resolve().parents[1] / "config"
    manifest = yaml.safe_load((config / "rule_pack_manifest.yaml").read_text())
    files = {name: yaml.safe_load((config / name).read_text()) for name in manifest["files"]}
    manifest.update(
        rule_pack_id=str(uuid4()), tenant_id=source.tenant_id, approved_by=None, approved_at=None
    )
    manifest["sha256"] = pack_content_hash(manifest, files)
    assert validate_rulepack(manifest, files, [f"GAP-{i:03}" for i in range(1, 11)]).ok
    pack = snapshot_from_validated(manifest, files)
    extractor = OfflineClaimFixture(manifest["sha256"])
    discovery = discover_atomic_claims(
        graph,
        ClaimScope(
            source.tenant_id,
            source.document_version_id,
            profile.parse_manifest_id,
            "declared_subset",
            (24,),
        ),
        extractor=extractor,
    )
    assert len(discovery.claims) == 2
    assert all(ref.page_num == 24 for claim in discovery.claims for ref in claim.source_refs)

    aliases = {
        c.source.source_native_id: b.source_id
        for b in graph.blocks
        for c in b.candidates
        if b.page_num == 97 and c.table_native_id == "p97-t0"
    }
    table = next(
        b
        for b in graph.blocks
        if b.page_num == 97
        and b.kind == "table"
        and any(c.source.source_native_id == "p97-t0" for c in b.candidates)
    )
    # Only rows with explicit metric AND geography cells; never fill merged blanks.
    assignments = tuple(
        {
            role: aliases[native]
            for role, native in {
                "metric_raw": f"p97-t0-r{row}-c0",
                "subject": f"p97-t0-r{row}-c1",
                "unit_raw": f"p97-t0-r{row}-c2",
                "reporting_period": f"p97-t0-r0-c{col}",
                "value_raw": f"p97-t0-r{row}-c{col}",
            }.items()
        }
        for row in (1, 5, 9)
        for col in (3, 4, 5)
    )
    normalized = normalize_table_bindings(
        graph, table_id=table.source_id, bindings=assignments, tenant_id=source.tenant_id
    )
    assert len(normalized.observations) == 9
    assert all(o.quality == "unverified" for o in normalized.observations)
    decisions, packets = [], []
    for claim in discovery.claims:
        packet = retrieve_evidence(
            claim,
            graph,
            OfflineLexicalSearch(graph),
            tenant_id=source.tenant_id,
            run_id=str(uuid4()),
            index_generation="offline-selected-appendix-v1",
            rulepack=pack,
            document_context={},
            token_counter=lambda text: len(text),
            max_tokens=12000,
        )
        packets.append(packet.to_dict())
        # Guard replay only: no verified facts or real replica calls exist yet.
        track = "goal" if "2030년 목표" in claim.quote else "performance"
        tags = ConfirmedTags(
            source.tenant_id,
            source.document_version_id,
            claim.claim_id,
            track,
            (),
            1,
            packet.packet_sha256,
            extractor.profile.model_sha256,
            extractor.profile.prompt_sha256,
            tuple(canonical_hash({"offline_fixture_replica": i}) for i in (1, 2, 3)),
            pack.ontology_version,
        )
        context = RuleContext(
            source.tenant_id,
            source.document_version_id,
            claim.claim_id,
            packet.packet_sha256,
            local_synthetic=True,
        )
        decision = evaluate(tags, context, pack)
        assert decision.evidence_grade is None and decision.label is None
        decisions.append(dict(claim=claim.quote, **asdict(decision)))
    result = dict(
        source_sha256=PDF_SHA256,
        parsed_pages=[24, 97, 117],
        claim_pages=[24],
        appendix_pages=[97, 117],
        fixture_tagging=True,
        live_model="not_run",
        vision="not_run",
        automatic_observations=len(
            normalize_tables(graph, tenant_id=source.tenant_id).observations
        ),
        explicit_binding_observations=[asdict(o) for o in normalized.observations],
        extraction=asdict(discovery),
        assignments=assignments,
        packets=packets,
        decisions=decisions,
        rulepack_sha256=manifest["sha256"],
        limitations=[
            "Selected case, not complete E coverage",
            "Cell-role tags are offline fixtures",
            "No source-quality approval; all grades remain null",
            "Raw unit subscript order is retained; no unit repair inferred",
        ],
    )
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    assert sha256(pdf.read_bytes()).hexdigest() == PDF_SHA256
    print(
        json.dumps(
            dict(
                pages=3,
                claims=2,
                bound_observations=9,
                decisions=[d["decision_status"] for d in decisions],
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pdf", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--java", default="java")
    args = cli.parse_args()
    run(args.pdf, args.output, args.java)
