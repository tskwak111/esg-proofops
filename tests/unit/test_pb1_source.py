import io
from hashlib import sha256
from uuid import uuid4

from proofops.adapters.local.upstage_ocr_profile_v7 import cell_proof
from proofops.adapters.parsing.upstage_document import candidate_batch
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact, fuse_candidates
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def fixture(value="15", *, raised=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 10 Tf 30 220 Td (Metric) Tj 150 0 Td (Unit) Tj "
        b"120 0 Td (2023) Tj 100 0 Td (2024) Tj ET "
        b"BT /F1 10 Tf 30 190 Td (Scope 1) Tj 150 0 Td (tCO2eq) Tj "
        b"120 0 Td (10) Tj 100 0 Td (15) Tj ET"
    )
    if raised:
        stream.set_data(
            stream.get_data().replace(
                b"100 0 Td (15) Tj ET", b"100 0 Td (15) Tj /F1 8 Tf 11 3 Td (1) Tj ET"
            )
        )
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    data = out.getvalue()
    tenant = str(uuid4())
    source = SourceArtifact(
        tenant, str(uuid4()), str(uuid4()), sha256(data).hexdigest(), "v1", data
    )
    profile = ParserProfile(str(uuid4()), parser_mode="upstage", table_claims_profile="pb1-v1")
    html = (
        "<table><tr><td>Metric</td><td>Unit</td><td>2023</td><td>2024</td></tr>"
        f"<tr><td>Scope 1</td><td>tCO2eq</td><td>10</td><td>{value}</td></tr></table>"
    )
    batch, _ = candidate_batch(
        source,
        profile,
        (1,),
        [
            dict(
                model="document-parse-260128",
                usage=dict(pages=1, standard=[1]),
                elements=[
                    dict(
                        page=1,
                        category="table",
                        content=dict(text="", html=html),
                        coordinates=[
                            dict(x=0.02, y=0.15),
                            dict(x=0.85, y=0.15),
                            dict(x=0.85, y=0.45),
                            dict(x=0.02, y=0.45),
                        ],
                    )
                ],
            )
        ],
        mode="standard",
        config_hash=profile.config_hash(),
    )
    graph = fuse_candidates((batch,), tenant_id=tenant)
    table = next(b for b in graph.blocks if b.kind == "table")
    start = table.normalized_text.index("Scope")
    ref = table.source_ref(
        normalized_char_start=start, normalized_char_end=len(table.normalized_text)
    )
    return graph, source, ref


def test_original_cells_year_and_unit_verified():
    graph, source, ref = fixture()
    proof = cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    assert proof["status"] == "verified"
    assert [(p["row"], p["column"]) for p in proof["cell_proofs"]] == [
        (1, 0),
        (1, 1),
        (1, 2),
        (1, 3),
        (0, 3),
    ]
    assert proof["cell_proofs"][-1]["source_ref"]["quote"] == "2024"


def test_wrong_number_cannot_be_verified():
    graph, source, ref = fixture("16")
    proof = cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    assert proof["status"] == "unresolved"


def test_wrong_tenant_is_refused():
    graph, source, ref = fixture()
    proof = cell_proof(graph, source.content, [ref], tenant_id=str(uuid4()))[0]
    assert proof["status"] == "unresolved"


def test_pb1_hash_changes_and_hf1_policy_remains_readable():
    from proofops.application.analysis_profile import V2_HF1_POLICY, V2_POLICY, policy_for
    from proofops.domain.provenance import canonical_hash
    from proofops_agent.upstage_extraction import _profile_with_options

    assert canonical_hash(V2_HF1_POLICY) != canonical_hash(V2_POLICY)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_HF1_POLICY))
        == V2_HF1_POLICY
    )
    assert (
        _profile_with_options().rule_sha256
        != _profile_with_options(extraction_pb1=True).rule_sha256
    )
    assert ParserProfile(str(uuid4())).config_snapshot().get("table_claims_profile") is None


def test_raised_marker_is_not_part_of_numeric_value():
    from proofops.adapters.parsing.pb1_cell_grounding import ground_cells

    cells = [dict(text="151", row=0, column=0, row_span=1, column_span=1)]
    words = [dict(text="151", x0=10, top=10, x1=30, bottom=20)]
    chars = [
        dict(text="1", x0=10, top=10, x1=16, bottom=20, size=10),
        dict(text="5", x0=16, top=10, x1=22, bottom=20, size=10),
        dict(text="1", x0=22, top=7, x1=26, bottom=13, size=6),
    ]
    assert ground_cells(cells, words, (0, 0, 100, 100), chars=chars) == [None]


def test_raised_marker_stays_unlocated_through_parser_and_verifier():
    graph, source, ref = fixture("151", raised=True)
    values = [b for b in graph.blocks if b.kind == "table_cell" and b.raw_text == "151"]
    assert len(values) == 1 and values[0].bbox is None
    assert (
        cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "unresolved"
    )
