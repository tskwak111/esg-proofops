"""Operator creation uses a real reviewed synthetic run and immutable PDF bytes."""

from copy import deepcopy
from dataclasses import asdict

import pytest
from proofops.adapters.local.reconciliation_store import (
    LocalReconciliationStore,
    ReconciliationRejected,
)

from evaluation.reconciliation_from_claim import create_case_from_claim
from tests.reconciliation.test_filings import listing, pin
from tests.reconciliation.test_product_store import TENANT, auth, prepare_bundle

BOUNDARY_LITERAL = '["A","B"]'
# The synthetic extractor splits " and " clauses, so the literal is its own (first) claim;
# verified_setup budgets only one claim's three tagger calls.
BOUNDARY_TEXT = BOUNDARY_LITERAL + " and group emissions boundary covers subsidiaries"


def boundary_pdf(text=BOUNDARY_TEXT, *, pages=1):
    """Real PDF bytes; the synthetic parser reads page 1, later pages stay uncited."""
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (" + text.encode() + b") Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    for _ in range(pages - 1):
        writer.add_blank_page(width=600, height=800)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    from tests.integration.test_local_tag_runner import verified_setup

    monkeypatch = MonkeyPatch()
    try:
        monkeypatch.setattr("tests.acceptance.test_parsing.pdf", lambda: boundary_pdf(pages=2))
        service, run_id, runner, _, _ = verified_setup(
            tmp_path_factory.mktemp("from-claim"), monkeypatch
        )
        assert (
            runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
        ), runner.tags.load_snapshot(TENANT, run_id)
        with service.store.jobs._transaction() as db:
            heads = service.store.jobs._all(db, TENANT, run_id, "review_head")
        claims = {h["claim_id"]: runner.claims.get(TENANT, run_id, h["claim_id"]) for h in heads}
        head = next(h for h in heads if claims[h["claim_id"]].quote == BOUNDARY_LITERAL)
        claim = claims[head["claim_id"]]
        boundary = claim.source_refs[0]
        assert boundary.quote == BOUNDARY_LITERAL and claim.source_quality == "verified"
        elements = [
            dict(
                element_id=eid,
                state="present" if eid == "M2" else "unknown",
                evidence_refs=[asdict(boundary)] if eid == "M2" else [],
                normalized_value=BOUNDARY_LITERAL if eid == "M2" else None,
                credited_from=None,
                reason_code=None,
            )
            for eid in ("M1", "M2", "M3", "M4", "M5", "M6")
        ]
        runner.reviews.resolve_review(
            auth("reviewer"),
            head["review_id"],
            dict(
                base_tag_revision=1,
                track="management",
                reason="Synthetic explicit boundary selection",
                elements=elements,
            ),
            '"1"',
            "from-claim-review-0001",
            reopen=False,
        )
        yield dict(
            service=service,
            run_id=run_id,
            claim_id=claim.claim_id,
            claim=claim,
            claims=runner.claims,
            tags=runner.tags,
            track="management",
            company_id=service.store.snapshot(TENANT, run_id)["document"]["company"]["company_id"],
        )
    finally:
        monkeypatch.undo()


def operator_inputs(reviewed, tmp_path, name="c1-same-entities", *, link=True):
    """Operator-side inputs: prepared financial draft, company link and DART pin."""
    service = reviewed["service"]
    store = LocalReconciliationStore(
        service.store.path,
        tmp_path / "managed",
        run_store=service.store,
        claims=reviewed["claims"],
        tags=reviewed["tags"],
    )
    draft, root = prepare_bundle(tmp_path, reviewed, name=name)
    draft["policy"].update(approved=False, approved_by=None, approved_on=None)
    draft["packet"]["identity"].update(dart_corp_code="00126380", rcept_no="20250313000532")
    manifest, _ = listing(as_of="20250630")
    try:
        if link:
            store.link_company(
                auth(),
                reviewed["company_id"],
                "00126380",
                registry=service.uploads.registry,
                reason="Synthetic operator identity fixture",
            )
    except ReconciliationRejected:
        assert store.company_link(auth(), reviewed["company_id"])["corp_code"] == "00126380"
    return dict(
        store=store,
        uploads=service.uploads,
        auth=auth(),
        run_id=reviewed["run_id"],
        claim_id=reviewed["claim_id"],
        draft=draft,
        artifact_root=root,
        pin=pin(manifest),
    )


@pytest.fixture
def prepared(reviewed, tmp_path):
    return operator_inputs(reviewed, tmp_path)


def test_current_claim_creates_pending_case_using_original_pdf(prepared, reviewed):
    result = create_case_from_claim(**prepared)
    assert result["review_state"] == "pending"
    assert result["policy_approved"] is False and result["policy_approval"] is None
    assert result["provenance"]["tag_revision"] == 2
    assert result["provenance"]["claim_track"] == "management"
    packet = result["packet"]
    assert packet["item"] == "C1" and packet["claim"]["track"] == "management"
    assert packet["claim"]["trigger_elements"] == ["organizational_boundary"]
    assert packet["sustainability"]["normalized"] == BOUNDARY_LITERAL
    assert packet["sustainability"]["kind"] == "entity_set"
    claim = reviewed["claim"]
    original = reviewed["service"].uploads.read_original(TENANT, claim.document_version_id)
    assert original.startswith(b"%PDF-")
    sr = [s for s in result["sources"] if s["document_id"] == claim.document_version_id]
    assert sr and all(s["format"] == "pdf" and s["locator"] == "page:1" for s in sr)
    stored, _, digest = prepared["store"].source_content(
        auth(), result["case_id"], sr[0]["source_id"]
    )
    assert stored == original and digest == claim.source_sha256
    financial = [s for s in result["sources"] if s["document_id"] != claim.document_version_id]
    assert financial and {s["document_role"] for s in financial} == {"financial"}
    documents = result["provenance"]["review_evidence"]["documents"]
    assert all(d["period_binding_required"] is True for d in documents.values())
    assert all(d["binding_state"] == "draft" for d in documents.values())
    # Coverage units come from every physical page of the staged bytes, not cited pages.
    report = documents[claim.document_version_id]
    assert report["coverage_units"] == [
        dict(kind="page", unit_id="page-1", locator="page:1"),
        dict(kind="page", unit_id="page-2", locator="page:2"),
    ]
    assert report["coverage_catalog"] == dict(state="complete", source="pdf_pages")
    assert {b["coverage_unit_id"] for b in report["source_bindings"].values()} == {"page-1"}
    # The text financial fixture has no unit catalog: coverage stays explicitly incomplete.
    (filing,) = [d for d in documents.values() if d["document_role"] == "financial"]
    assert "coverage_units" not in filing
    assert filing["coverage_catalog"] == dict(state="incomplete", reason="unit_catalog_missing")
    assert all("coverage_unit_id" not in b for b in filing["source_bindings"].values())
    pinned = filing["filing_pin"]
    assert pinned["rcept_no"] == "20250313000532" and pinned["corp_code"] == "00126380"
    assert pinned["as_of"] == "20250630" and pinned["operator"] == "operator-1"
    assert pinned["pin_history_length"] == 1 and len(pinned["manifest_sha256"]) == 64
    assert "filing_pin" not in report


@pytest.mark.parametrize("catalog", ["consistent", "duplicate_unit", "unmapped_binding"])
def test_supplied_non_pdf_catalog_kept_only_when_consistent(prepared, catalog):
    draft = prepared["draft"]
    financial_id = draft["packet"]["identity"]["financial_document_version"]
    template = draft["documents"][financial_id]
    units = [
        dict(kind="note", unit_id="note-1", locator="note:1"),
        dict(kind="note", unit_id="note-2", locator="note:2"),
    ]
    if catalog == "duplicate_unit":
        units[1]["unit_id"] = "note-1"
    template["coverage_units"] = units
    for binding in template["source_bindings"].values():
        binding["coverage_unit_id"] = "note-9" if catalog == "unmapped_binding" else "note-1"
    result = create_case_from_claim(**prepared)
    filing = result["provenance"]["review_evidence"]["documents"][financial_id]
    if catalog == "consistent":
        assert filing["coverage_units"] == units
        assert filing["coverage_catalog"] == dict(state="complete", source="supplied")
        assert {b["coverage_unit_id"] for b in filing["source_bindings"].values()} == {"note-1"}
    else:
        assert "coverage_units" not in filing
        assert filing["coverage_catalog"]["state"] == "incomplete"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("c5", "stage_disabled"),
        ("approval", "imported_policy_approval_forbidden"),
        ("registry", "imported_policy_approval_forbidden"),
        ("receipt", "filing_identity_mismatch"),
        ("year", "filing_period_mismatch"),
        ("synthetic", "SYNTHETIC_SCOPE_MISMATCH"),
    ],
)
def test_untrusted_operator_input_rejected(prepared, change, reason):
    prepared["draft"] = deepcopy(prepared["draft"])
    draft = prepared["draft"]
    if change == "c5":
        draft["packet"]["item"] = "C5"
    elif change == "approval":
        draft["policy"]["approved"] = True
    elif change == "registry":
        draft["policies"] = {"imported": {"approved": True}}
    elif change == "receipt":
        draft["packet"]["identity"]["rcept_no"] = "20251210000195"
    elif change == "year":
        draft["packet"]["identity"]["financial_fiscal_year"] = 2023
    elif change == "synthetic":
        draft["packet"]["synthetic"] = False
    with pytest.raises(ReconciliationRejected, match=reason):
        create_case_from_claim(**prepared)


@pytest.mark.parametrize(
    "change,error",
    [
        ("corp", "filing_identity_mismatch"),
        ("pin_corp", "invalid_filing_provenance"),
        ("pin_as_of", "pin_history_integrity_mismatch"),
        ("path", "path_outside_root"),
        ("financial_bytes", "artifact_hash_mismatch"),
        ("wrong_item", "no_matching_item_trigger"),
    ],
)
def test_mismatched_company_pin_path_hash_or_item_is_refused(prepared, change, error):
    from proofops.adapters.reconciliation.files import SourceReadError

    draft = prepared["draft"]
    store, before = prepared["store"], None
    if change == "corp":
        draft["packet"]["identity"]["dart_corp_code"] = "00000001"
    elif change == "pin_corp":
        prepared["pin"] = dict(deepcopy(prepared["pin"]), corp_code="00000001")
    elif change == "pin_as_of":
        prepared["pin"] = dict(deepcopy(prepared["pin"]), as_of="20250701")
    elif change == "path":
        # Even byte-identical content outside the operator root is never followed.
        entry = draft["artifacts"][next(iter(draft["artifacts"]))]
        outside = prepared["artifact_root"].parent / "outside.txt"
        outside.write_bytes((prepared["artifact_root"] / entry["path"]).read_bytes())
        entry["path"] = "../outside.txt"
    elif change == "financial_bytes":
        for entry in draft["artifacts"].values():
            (prepared["artifact_root"] / entry["path"]).write_bytes(b"changed")
    elif change == "wrong_item":
        draft["packet"]["item"] = "C2"
    before = store.list_for_claim(auth(), prepared["run_id"], prepared["claim_id"])
    with pytest.raises((ReconciliationRejected, SourceReadError, ValueError), match=error):
        create_case_from_claim(**prepared)
    assert store.list_for_claim(auth(), prepared["run_id"], prepared["claim_id"]) == before


def test_head_moving_during_preparation_is_refused_by_cas(prepared, monkeypatch):
    from scripts.linkage_exchange_cli import reviewed_head_tags as real_head

    calls = []

    def moving(*args, **kwargs):
        tags, revision = real_head(*args, **kwargs)
        calls.append(revision)
        return tags, revision + (len(calls) > 1)

    monkeypatch.setattr("evaluation.reconciliation_from_claim.reviewed_head_tags", moving)
    with pytest.raises(ReconciliationRejected, match="TAG_HEAD_CHANGED"):
        create_case_from_claim(**prepared)
    assert len(calls) == 2


def test_pdf_tamper_rejected(prepared, monkeypatch):
    from proofops.adapters.parsing.opendataloader import ParseFailure

    monkeypatch.setattr(prepared["uploads"], "read_original", lambda *_: b"tampered")
    with pytest.raises(
        (ReconciliationRejected, ParseFailure),
        match="(ARTIFACT_UNVERIFIED|SOURCE_INTEGRITY_MISMATCH)",
    ):
        create_case_from_claim(**prepared)


def test_no_trigger_is_explicitly_blocked(prepared, monkeypatch):
    monkeypatch.setattr(
        "evaluation.reconciliation_from_claim.reviewed_head_tags", lambda *a, **kw: (None, 2)
    )
    with pytest.raises(ReconciliationRejected):
        create_case_from_claim(**prepared)


# --------------------------------------------------------------------------- #
# C2: a second real reviewed run (performance P1 literal with an explicit range)
# --------------------------------------------------------------------------- #

C2_TEXT = "2024-01-01 ~ 2024-12-31 Scope 1 emissions 1234 tCO2e"


def c2_pdf():
    return boundary_pdf(C2_TEXT)


@pytest.fixture(scope="module")
def reviewed_c2(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    from tests.integration import test_run_lifecycle as lifecycle
    from tests.integration.test_local_tag_runner import verified_setup

    monkeypatch = MonkeyPatch()
    try:
        original_setup = lifecycle.setup_upload

        def period_upload(directory, **options):
            uploads, document, payload, metadata = original_setup(directory, **options)
            metadata.update(report_year=2024, period_start="2024-01-01", period_end="2024-12-31")
            return uploads, document, payload, metadata

        monkeypatch.setattr(lifecycle, "setup_upload", period_upload)
        monkeypatch.setattr("tests.acceptance.test_parsing.pdf", c2_pdf)
        service, run_id, runner, _, _ = verified_setup(
            tmp_path_factory.mktemp("from-claim-c2"), monkeypatch
        )
        assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
        with service.store.jobs._transaction() as db:
            head = service.store.jobs._all(db, TENANT, run_id, "review_head")[0]
        claim = runner.claims.get(TENANT, run_id, head["claim_id"])
        assert claim.quote == C2_TEXT
        ref = claim.source_refs[0]
        elements = [
            dict(
                element_id=eid,
                state="present" if eid == "P1" else "unknown",
                evidence_refs=[asdict(ref)] if eid == "P1" else [],
                normalized_value=ref.quote if eid == "P1" else None,
                credited_from=None,
                reason_code=None,
            )
            for eid in ("P1", "P2", "P3", "P4", "P5", "P6")
        ]
        runner.reviews.resolve_review(
            auth("reviewer"),
            head["review_id"],
            dict(
                base_tag_revision=1,
                track="performance",
                reason="Synthetic explicit quantitative selection",
                elements=elements,
            ),
            '"1"',
            "from-claim-review-c2-01",
            reopen=False,
        )
        yield dict(
            service=service,
            run_id=run_id,
            claim_id=claim.claim_id,
            claim=claim,
            claims=runner.claims,
            tags=runner.tags,
            track="performance",
            company_id=service.store.snapshot(TENANT, run_id)["document"]["company"]["company_id"],
        )
    finally:
        monkeypatch.undo()


def test_c2_real_review_creates_pending_case_with_source_bound_period(reviewed_c2, tmp_path):
    from proofops.application.linkage_exchange import C2PeriodContext

    claim = reviewed_c2["claim"]
    period = C2PeriodContext("2024-01-01/2024-12-31", claim.source_refs[0].source_id, C2_TEXT)
    # This run's company has no operator DART link yet: no case, no guessed corp code.
    unlinked = operator_inputs(reviewed_c2, tmp_path / "unlinked", "c2-same-period", link=False)
    with pytest.raises(ReconciliationRejected, match="unresolved_company_identity"):
        create_case_from_claim(**unlinked, c2_period_context=period)
    kwargs = operator_inputs(reviewed_c2, tmp_path, "c2-same-period")
    with pytest.raises(ReconciliationRejected, match="missing_c2_period_context"):
        create_case_from_claim(**kwargs)
    result = create_case_from_claim(**kwargs, c2_period_context=period)
    assert result["review_state"] == "pending" and result["policy_approved"] is False
    packet = result["packet"]
    assert packet["item"] == "C2" and packet["claim"]["track"] == "performance"
    assert packet["claim"]["trigger_elements"] == ["quantitative_value"]
    assert packet["sustainability"]["kind"] == "period"
    assert packet["sustainability"]["normalized"] == "2024-01-01/2024-12-31"
    sid = packet["sustainability"]["source_id"]
    documents = result["provenance"]["review_evidence"]["documents"]
    assert documents[claim.document_version_id]["fact_bindings"][sid]["period_binding"] == {
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
    }
    unsupported = C2PeriodContext("2023-01-01/2023-12-31", period.source_id, C2_TEXT)
    with pytest.raises(ReconciliationRejected, match="c2_period_not_supported_by_source"):
        create_case_from_claim(**kwargs, c2_period_context=unsupported)


# --------------------------------------------------------------------------- #
# C3/C4: typed confirmed-tag BOUNDARY fixtures, not real producers
#
# No main producer emits `currency_amount` or `revenue_share` facts (see
# linkage_exchange.TRIGGER_TAG_MAP), so no real review can trigger C3/C4. These
# tests run a real upload/parse/extract/tag pipeline for the claim and its PDF,
# prove the real head is blocked, then inject an explicitly typed ConfirmedTags
# at the `reviewed_head_tags` boundary only to exercise the operator path. The
# store still re-checks the real claim head revision, track and PDF bytes.
# --------------------------------------------------------------------------- #

TYPED = {
    "C3": ("10000000000", "currency_amount", "c3-policy-unresolved"),
    "C4": ("green-products", "revenue_share", "c4-definition-and-method"),
}


@pytest.fixture(scope="module", params=sorted(TYPED))
def typed_run(request, tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    from tests.integration.test_local_tag_runner import verified_setup

    item = request.param
    literal, fact_name, example = TYPED[item]
    monkeypatch = MonkeyPatch()
    try:
        text = literal + " and emissions programme disclosure"
        monkeypatch.setattr("tests.acceptance.test_parsing.pdf", lambda: boundary_pdf(text))
        service, run_id, runner, _, _ = verified_setup(
            tmp_path_factory.mktemp(f"typed-{item}"), monkeypatch
        )
        assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
        with service.store.jobs._transaction() as db:
            heads = service.store.jobs._all(db, TENANT, run_id, "review_head")
        claim = next(
            c
            for c in (runner.claims.get(TENANT, run_id, h["claim_id"]) for h in heads)
            if c.quote == literal
        )
        yield dict(
            service=service,
            run_id=run_id,
            claim_id=claim.claim_id,
            claim=claim,
            claims=runner.claims,
            tags=runner.tags,
            track="performance",
            item=item,
            fact_name=fact_name,
            example=example,
            company_id=service.store.snapshot(TENANT, run_id)["document"]["company"]["company_id"],
        )
    finally:
        monkeypatch.undo()


def typed_boundary_tags(run, revision):
    """Explicit typed boundary: a fact name no main producer emits today."""
    from proofops.domain.rules.engine import ConfirmedFact, ConfirmedTags

    claim = run["claim"]
    fact = ConfirmedFact(
        run["fact_name"],
        "present",
        claim.source_refs,
        TENANT,
        True,
        True,
        normalized_value=claim.quote,
    )
    inputs = run["tags"].load_inputs(TENANT, run["run_id"], claim.claim_id)
    first = inputs.tag_runs[0]
    return ConfirmedTags(
        TENANT,
        claim.document_version_id,
        claim.claim_id,
        run["track"],
        (fact,),
        revision,
        inputs.packet.packet_sha256,
        first.model_sha256,
        first.prompt_sha256,
        inputs.consensus.replicate_hashes,
        inputs.rulepack.ontology_version,
    )


def test_c3_c4_real_head_has_no_trigger_and_typed_boundary_reaches_pending_case(
    typed_run, tmp_path, monkeypatch
):
    from scripts.linkage_exchange_cli import reviewed_head_tags as real_head

    kwargs = operator_inputs(typed_run, tmp_path, typed_run["example"])
    # Real head: revision-1 unconfirmed consensus carries no confirmed tags.
    with pytest.raises(ReconciliationRejected, match="missing_confirmed_tags"):
        create_case_from_claim(**kwargs)
    tags, revision = real_head(
        typed_run["claims"],
        typed_run["claim"],
        tenant_id=TENANT,
        run_id=typed_run["run_id"],
        claim_id=typed_run["claim_id"],
    )
    assert tags is None and revision == 1
    monkeypatch.setattr(
        "evaluation.reconciliation_from_claim.reviewed_head_tags",
        lambda *a, **kw: (typed_boundary_tags(typed_run, revision), revision),
    )
    if typed_run["item"] == "C4":
        # The example's definition/method ids name fixture sources this claim never cites.
        with pytest.raises(ReconciliationRejected, match="invalid_reconciliation_packet"):
            create_case_from_claim(**kwargs)
        sid = "sr-" + typed_run["claim"].source_refs[0].source_id
        context = kwargs["draft"]["packet"]["c4_context"]
        context.update(definition_source_ids=[sid], calculation_source_ids=[sid])
    result = create_case_from_claim(**kwargs)
    assert result["review_state"] == "pending" and result["policy_approved"] is False
    packet = result["packet"]
    assert packet["item"] == typed_run["item"]
    assert packet["sustainability"]["normalized"] == typed_run["claim"].quote
    assert result["provenance"]["tag_revision"] == revision
    # A stale boundary revision is still refused by the store's own head CAS.
    monkeypatch.setattr(
        "evaluation.reconciliation_from_claim.reviewed_head_tags",
        lambda *a, **kw: (typed_boundary_tags(typed_run, revision + 1), revision + 1),
    )
    with pytest.raises(ReconciliationRejected, match="STALE_CLAIM_HEAD"):
        create_case_from_claim(**kwargs)
