"""RB3's 4460-token aggregate must not fence the next replica."""

from dataclasses import replace

from proofops.application.budget import BudgetLimits, RoleLimit, TokenUsage, record_usage

from tests.acceptance.test_cost import CALL, RUN, TENANT, reserve, seeded


def test_two_schema_responses_fit_logical_reservation_and_next_replica(tmp_path):
    from proofops.application.tagging.service import output_reservation_tokens

    output = output_reservation_tokens(model_id="gpt-6-luna", max_tokens=4096, synthetic=False)
    assert output == 8192
    limits = BudgetLimits(100000, 32768, (RoleLimit("tagger", 10, 32768, 8192, 40960),), 3)
    usage = seeded(tmp_path / "usage.sqlite", limits)
    assert reserve(usage, max_output_tokens=output, price=None)
    record_usage(usage, CALL, TokenUsage(100, 4460, 0, 0, 1, "succeeded", "two-attempts"), now=2)
    assert reserve(
        usage,
        replace(CALL, request_id="replica-2", replicate_id=2),
        max_output_tokens=output,
        price=None,
    )
    assert usage.cost_data(TENANT, RUN)[0]["reservation"]["max_output_tokens"] == 8192


def test_actual_tag_replica_path_reserves_retry_total(tmp_path):
    from proofops.adapters.aws.usage import LocalSQLiteUsageStore
    from proofops.application.ports.models import ModelBinding
    from proofops.application.tagging.service import RawTagResponse

    from tests.acceptance.test_tagging import execute, setup

    data = setup(tmp_path)
    data["settings"] = replace(
        data["settings"],
        binding=ModelBinding("fx5-fake-http", "tagger", False),
        model_id="gpt-6-luna",
        max_tokens=4096,
    )
    usage = LocalSQLiteUsageStore(tmp_path / "aggregate.sqlite")
    usage.create_budget(
        data["tenant_id"],
        data["packet"].to_dict()["run_id"],
        data["context"].claim.document_version_id,
        BudgetLimits(100000, 32768, (RoleLimit("tagger", 10, 32768, 8192, 40960),)),
    )
    data["usage_store"] = usage
    original = data["invoke"]

    def invoke(request):
        result = original(request)
        return RawTagResponse(
            result.raw_response_json,
            replace(result.usage, output_tokens=4460 if request["replicate_id"] == 1 else 10),
            False,
        )

    data.update(invoke=invoke, count_input_tokens=lambda request: 100)
    results = execute(data)
    assert [r.usage.output_tokens for r in results] == [4460, 10, 10]
    rows = usage.cost_data(data["tenant_id"], data["packet"].to_dict()["run_id"])
    assert len(rows) == 3
    assert all(r["reservation"]["max_output_tokens"] == 8192 for r in rows)
