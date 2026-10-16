from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import ClaimContext
from proofops.application.tagging.qt2_inventory import _candidate_element

from tests.acceptance.test_binding import span
from tests.acceptance.test_rules import pack
from tests.unit.test_k5_context import case


def fixture():
    text = "가상기업은 서울공장 ISO 14001 심사를 2024년에 완료했습니다."
    graph, claim = case([text], (0, text))
    full = claim.source_refs[0]
    dims = {
        k: span(full, v)
        for k, v in dict(
            entity="가상기업", facility="서울공장", metric="ISO 14001", reporting_period="2024년"
        ).items()
    }
    attrs = {
        k: asdict(dims[v])
        for k, v in dict(
            subject="entity", site="facility", metric="metric", period="reporting_period"
        ).items()
    }
    candidate = dict(
        element_id="M4",
        evidence_ref=asdict(full),
        votes={
            str(i): dict(state="present", evidence_ref=asdict(full), attributes=deepcopy(attrs))
            for i in (1, 2, 3)
        },
    )
    return graph, ClaimContext(claim, dims), candidate


def test_qt2_consumes_sc1_attribute_names_and_three_votes():
    graph, context, candidate = fixture()
    assert (
        _candidate_element(
            candidate, context, graph, tenant_id=graph.tenant_id, rulepack=pack()
        ).state
        == "present"
    )


@pytest.mark.parametrize(
    "change", ["null", "conflict", "missing_replica", "wrong_period", "unverified", "extra_axis"]
)
def test_qt2_inventory_cannot_fill_unknown_or_mismatched_axes(change):
    graph, context, candidate = fixture()
    if change == "null":
        candidate["votes"]["2"]["attributes"]["site"] = None
    if change == "conflict":
        candidate["votes"]["3"]["state"] = "conflict"
    if change == "missing_replica":
        candidate["votes"].pop("3")
    if change == "wrong_period":
        candidate["votes"]["1"]["attributes"]["period"] = candidate["votes"]["1"]["attributes"][
            "metric"
        ]
    if change == "unverified":
        context = replace(context, claim=replace(context.claim, source_quality="unverified"))
    if change == "extra_axis":
        context = replace(context, dimensions=dict(context.dimensions) | dict(scope=None))
    assert (
        _candidate_element(candidate, context, graph, tenant_id=graph.tenant_id, rulepack=pack())
        is None
    )
