"""SV1 pinned real pages and adversarial source-admission regressions."""

import io
import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.domain.values import SourceRef
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject

from tests.acceptance.test_parsing import TENANT, candidate
from tests.integration.test_claim_source_verification import geometry_pdf

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
FIXTURES = Path(__file__).parents[1] / "fixtures/claim_source_v3"


def verifier():
    from proofops.adapters.local import claim_source_verification_v3

    return claim_source_verification_v3


def real_inputs(company):
    data = json.loads((FIXTURES / (company + ".json")).read_text())
    source = (ROOT / data["source_path"]).read_bytes()
    assert sha256(source).hexdigest() == data["source_sha256"]
    batches = candidates_from_snapshot(data["batches"])
    graph = fuse_candidates(
        batches, tenant_id=batches[0].tenant_id, fusion_version=data["fusion_version"]
    )
    return source, graph, SourceRef(**data["ref"])


def synthetic(parser_text, native_text="ESG policy 10% achieved", annotation=None):
    source = geometry_pdf([(72, 720, native_text), (72, 680, "OTHER ROW 999 tonnes")])
    if annotation:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
        if "/AP" in annotation:
            appearance = annotation["/AP"]["/N"]
            annotation["/AP"][NameObject("/N")] = writer._add_object(appearance)
        writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
        output = io.BytesIO()
        writer.write(output)
        source = output.getvalue()
    batch = replace(
        candidate("sv1", [("P", "paragraph", parser_text, (70, 705, 400, 735), ())]),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    return source, graph, graph.blocks[0].source_ref()


def record(inputs):
    source, graph, ref = inputs
    return verifier().attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)[
        "records"
    ][0]


@pytest.mark.parametrize("company", ["naver", "sk"])
def test_real_pinned_pages_recover(company):
    source, graph, ref = real_inputs(company)
    from proofops.adapters.local import claim_source_verification as old

    before = old.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert before["records"][0]["status"] == "unresolved"
    receipt = verifier().attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    result = receipt["records"][0]
    assert result["status"] == "verified"
    assert result["ref"] == asdict(ref)  # immutable parser provenance
    assert result["canonical_quote"] == (
        " ".join(ref.quote.split()).replace("E SG", "ESG") if company == "naver" else ref.quote
    )
    assert result["normalization"]["parser_quote"] == ref.quote
    assert result["normalization"]["source_sha256"] == graph.source_sha256
    assert result["normalization"]["physical_page"] == ref.page_num


@pytest.mark.parametrize(
    "parser,native",
    [
        ("E SG policy 10% achieved", "ESG policy 10% achieved"),
        ("ESG policy 10% achieved", "E SG policy 10% achieved"),
    ],
)
def test_whitespace_adopts_native_quote(parser, native):
    r = record(synthetic(parser, native))
    assert r["status"] == "verified" and r["canonical_quote"] == native
    assert r["normalization"]["parser_quote"] == parser


@pytest.mark.parametrize(
    "parser,native",
    [
        ("E SX policy 10% achieved", "ESG policy 10% achieved"),
        ("ESG policy 1 0% achieved", "ESG policy 10% achieved"),
        ("ESG policy 10 % achieved", "ESG policy 10% achieved"),
        ("ESG policy 1 .0% achieved", "ESG policy 1.0% achieved"),
        ("ESG policy - 10% achieved", "ESG policy -10% achieved"),
        ("ESG policy 10 k g achieved", "ESG policy 10 kg achieved"),
        ("ESG policy 10 tCO2 e achieved", "ESG policy 10 tCO2e achieved"),
        ("ESG policy 10% achieved OTHER ROW 999 tonnes", "ESG policy 10% achieved"),
    ],
)
def test_forged_characters_numbers_units_and_other_row_stay_unresolved(parser, native):
    assert record(synthetic(parser, native))["status"] == "unresolved"


def test_wrong_page_and_ref_identity_rejected():
    source, graph, ref = real_inputs("naver")
    for forged in [
        replace(ref, page_num=84),
        replace(ref, quote=ref.quote.replace("환경", "환겅", 1)),
    ]:
        assert record((source, graph, forged))["status"] == "unresolved"
    with pytest.raises(ValueError):
        verifier().attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)


@pytest.mark.parametrize(
    "subtype,ap,overlap,expected",
    [
        ("/Link", False, True, "verified"),
        ("/Widget", False, True, "unresolved"),
        ("/Widget", True, True, "unresolved"),
        ("/Link", True, True, "unresolved"),
        ("/Widget", True, False, "verified"),
    ],
)
def test_only_actual_quote_glyph_annotation_overlap_blocks(subtype, ap, overlap, expected):
    from pypdf.generic import DecodedStreamObject

    box = (80, 713, 95, 730) if overlap else (70, 704, 95, 708)
    annotation = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject(subtype),
            NameObject("/Rect"): RectangleObject(box),
        }
    )
    if ap:
        appearance = DecodedStreamObject()
        appearance.set_data(b"0 0 0 rg 0 0 20 20 re f")
        appearance[NameObject("/BBox")] = RectangleObject((0, 0, 20, 20))
        appearance[NameObject("/Subtype")] = NameObject("/Form")
        annotation[NameObject("/AP")] = DictionaryObject({NameObject("/N"): appearance})
    assert record(synthetic("ESG policy 10% achieved", annotation=annotation))["status"] == expected


def test_optional_content_stays_unresolved():
    source, graph, ref = synthetic("ESG policy 10% achieved")
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer.root_object[NameObject("/OCProperties")] = DictionaryObject()
    stream = io.BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    batch = replace(graph.candidates[0], source_sha256=sha256(source).hexdigest())
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    assert record((source, graph, graph.blocks[0].source_ref()))["status"] == "unresolved"


def test_opt_in_dispatch_default_and_tamper():
    from argparse import Namespace

    from proofops.adapters.local import claim_source_policies, claim_source_verification

    from evaluation.local_upstage_pilot import claim_source_policy_for

    v3 = verifier()
    policy = v3.claim_source_policy()
    assert claim_source_policy_for(Namespace()) == claim_source_verification.claim_source_policy()
    assert claim_source_policy_for(Namespace(claim_source_profile="claim-source-v3")) == policy
    assert claim_source_policies.publication_reader(policy) is v3
    assert claim_source_policies.claim_source_reader(policy) is v3
    with pytest.raises(ValueError):
        claim_source_policies.claim_source_reader(dict(policy, verifier_sha256="f" * 64))


def test_replay_preserves_parser_offsets_and_attests_only_proven_spans():
    source, graph, ref = synthetic("E SG policy 10% achieved")
    v3 = verifier()
    receipt = v3.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    from proofops.application.claims import (
        Claim,
        ClaimDiscovery,
        ClaimScope,
        ExtractionProfile,
        ExtractionReceipt,
    )
    from proofops.application.evidence import span_citations

    profile = ExtractionProfile("a" * 64, "b" * 64, "c" * 64, True)
    er = ExtractionReceipt(ref.source_id, "d" * 64, None, None, profile, "failed")
    claim = Claim(
        "00000000-0000-4000-8000-000000000001",
        TENANT,
        graph.document_version_id,
        graph.parse_manifest_id,
        graph.source_sha256,
        ref.quote,
        (ref,),
        "unverified",
        (),
        er,
    )
    discovery = ClaimDiscovery(
        ClaimScope(
            TENANT, graph.document_version_id, graph.parse_manifest_id, "declared_subset", (1,)
        ),
        graph.source_sha256,
        (claim,),
        (),
        (),
        (),
        True,
        (),
    )
    recovered, scoped = v3.replay_claim_spans(receipt, graph, source, discovery, tenant_id=TENANT)
    assert recovered.claims[0].source_quality == "verified"
    assert scoped.blocks == graph.blocks
    assert (
        span_citations.verify_source_ref(ref, scoped, tenant_id=TENANT).verification_state
        == "verified"
    )
    receipt["records"][0]["canonical_quote"] = "forged"
    with pytest.raises(ValueError):
        v3.replay_claim_spans(receipt, graph, source, discovery, tenant_id=TENANT)


def test_real_full_naver_quote_with_ocr_character_error_stays_unresolved():
    source, graph, ref = real_inputs("naver")
    data = json.loads((FIXTURES / "naver.json").read_text())
    full = data["original_full_quote"]
    result = record((source, graph, replace(ref, quote=full, char_end=len(full))))
    assert result["status"] == "unresolved" and result["reason"] == "rendered_quote_unresolved"


def test_cannot_join_a_space_across_two_physical_lines():
    source = geometry_pdf([(72, 730, "ESG"), (72, 715, "policy")])
    batch = replace(
        candidate("sv1", [("P", "paragraph", "ESGpolicy", (70, 705, 200, 742), ())]),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    result = record((source, graph, graph.blocks[0].source_ref()))
    assert result["status"] == "unresolved"


def test_rendered_other_character_or_duplicate_cannot_be_folded(monkeypatch):
    v3 = verifier()
    for text in [
        "ESX policy 10% achieved",
        "ESG policy 10% achieved ESG policy 10% achieved",
        "ESG policy 1 0% achieved",
    ]:
        monkeypatch.setattr(v3, "_rendered_text", lambda *a, **k: dict(status="read", text=text))
        assert record(synthetic("E SG policy 10% achieved"))["status"] == "unresolved"


def test_normalization_offsets_address_the_original_parser_quote():
    v3 = verifier()
    parser = "E  SG policy"
    mapped = v3._canonical(parser, "ESG policy")
    assert mapped is not None
    assert "".join(parser[i] for i in mapped["canonical_to_parser"]) == "ESGpolicy"


def test_worker_publishes_and_reopens_opt_in_v3(tmp_path, monkeypatch):
    from proofops.adapters.local import claim_source_verification as old
    from proofops.adapters.local.claim_store import LocalClaimStore
    from proofops.adapters.local.run_artifacts import load_run_graph
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.application.ports.jobs import JobMessage

    from tests.integration import test_run_lifecycle as lifecycle
    from tests.integration.test_real_extract_runner import FakeProbe, real_setup

    v3 = verifier()
    original = lifecycle.setup

    def configured(path):
        service, body = original(path)
        service.claim_source_policy = v3.claim_source_policy()
        return service, body

    monkeypatch.setattr(lifecycle, "setup", configured)

    def reading(*a, **k):
        return dict(status="read", text="Page 1 emissions 1234 tCO2e")

    monkeypatch.setattr(old, "_rendered_text", reading)
    monkeypatch.setattr(v3, "_rendered_text", reading)
    quote = "e missions 1234 tCO2e"
    probe = FakeProbe(json.dumps({"claims": [quote]}))
    service, run_id, runner, now, probe = real_setup(tmp_path, monkeypatch, limit=1, probe=probe)
    base = load_run_graph(
        service.store, service.uploads, runner.parser, tenant_id=TENANT, run_id=run_id
    )
    batch = candidate(
        "sv1-worker", [("P", "paragraph", "Page 1 " + quote, (70, 710, 300, 740), ())]
    )
    batch = replace(
        batch,
        document_version_id=base.document_version_id,
        parse_manifest_id=base.parse_manifest_id,
        source_sha256=base.source_sha256,
        blocks=tuple(
            replace(
                b,
                source=replace(
                    b.source,
                    document_version_id=base.document_version_id,
                    parse_manifest_id=base.parse_manifest_id,
                ),
            )
            for b in batch.blocks
        ),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    for module in ("proofops_worker.extract_runner", "proofops.adapters.local.claim_store"):
        monkeypatch.setattr(module + ".load_run_graph", lambda *a, **k: graph)
    run = service.store.jobs.get_run(TENANT, run_id)
    parse_before = service.store.jobs.read_checkpoint(JobMessage(**run["parse_job"]))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    envelope, discovery, scoped = runner.claims.load_evidence(TENANT, run_id)
    receipt = envelope["claim_source_attestation"]
    assert receipt["schema"] == v3.SCHEMA
    assert receipt["records"][0]["canonical_quote"] == "emissions 1234 tCO2e"
    assert any(c.source_quality == "verified" for c in discovery.claims)
    assert all(b.quality != "verified" for b in scoped.blocks)
    reopened = LocalClaimStore(
        LocalSQLiteRunStore(service.store.path), service.uploads, runner.parser
    )
    assert reopened.load(TENANT, run_id) == discovery
    assert service.store.jobs.read_checkpoint(JobMessage(**run["parse_job"])) == parse_before
    assert len(probe.calls) == 1  # local fake extractor, no model transport


def test_spacing_inside_a_numeric_unit_is_blocked_without_unit_allowlist():
    assert (
        record(synthetic("ESG policy 10 M J achieved", "ESG policy 10 MJ achieved"))["status"]
        == "unresolved"
    )
