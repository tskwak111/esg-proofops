"""Offline kit/IAM syntax and safety contract, or existing private runtime validation."""

import json
import re
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def check_kit():
    from jsonschema import Draft202012Validator

    policy = json.loads((HERE / "iam-policy.json").read_text())
    schema = json.loads((HERE / "iam-policy.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(policy)
    assert set(policy) == {"Version", "Statement"} and policy["Version"] == "2012-10-17"
    assert isinstance(policy["Statement"], list) and policy["Statement"]
    assert (
        len(json.dumps(policy, separators=(",", ":"))) <= 6144
    ), "Customer-managed policy size limit"
    sids = set()
    for s in policy["Statement"]:
        assert set(s) <= {"Sid", "Effect", "Action", "Resource", "Condition"}
        assert (
            s["Effect"] == "Allow"
            and re.fullmatch(r"[a-zA-Z0-9]+", s["Sid"])
            and s["Sid"] not in sids
        )
        sids.add(s["Sid"])
        assert isinstance(s["Action"], list) and isinstance(s["Resource"], list)
        assert s["Action"] and s["Resource"]
        for action in s["Action"]:
            assert re.fullmatch(
                r"(ec2|ssm|servicequotas|budgets):[A-Za-z]+", action
            ), "Only exact required IAM actions"
        for resource in s["Resource"]:
            assert resource == "*" or re.fullmatch(
                r"arn:aws:(ec2|ssm|servicequotas|budgets):[^:]*:[^:]*:.+", resource
            )
            assert "ACCOUNT_ID" not in resource
            assert resource != "*" or all(
                a.startswith("ec2:Describe") for a in s["Action"]
            ), "Writes need resource ARNs"
        condition = s.get("Condition", {})
        assert all(
            op
            in {
                "StringEquals",
                "StringLike",
                "Bool",
                "NumericEquals",
                "ForAllValues:StringEquals",
                "Null",
            }
            for op in condition
        )
        assert all(isinstance(values, dict) for values in condition.values())
        if not all(a.startswith("budgets:") for a in s["Action"]):
            assert condition["StringEquals"]["aws:RequestedRegion"] == "ap-northeast-2"
        if "ForAllValues:StringEquals" in condition:
            assert condition["Null"]["aws:TagKeys"] == "false"
        for action in s["Action"]:
            if action in {
                "ec2:TerminateInstances",
                "ec2:StopInstances",
                "ec2:DeleteSecurityGroup",
                "ec2:DeleteKeyPair",
                "ec2:ReleaseAddress",
                "ec2:DisassociateAddress",
            }:
                assert condition["StringEquals"]["aws:ResourceTag/Project"] == "proofops-r108"
    bysid = {s["Sid"]: s for s in policy["Statement"]}
    assert (
        bysid["OnlyT4gMediumIMDSv2"]["Condition"]["StringEquals"]["ec2:InstanceType"]
        == "t4g.medium"
    )
    assert bysid["TagOnlyAtKitCreation"]["Condition"]["StringEquals"]["ec2:CreateAction"] == [
        "RunInstances",
        "CreateSecurityGroup",
        "ImportKeyPair",
        "AllocateAddress",
    ]
    assert "aarch64" in (HERE / "cloud-init.sh").read_text()
    assert (HERE / "compose.yaml").resolve() == (HERE / "../lightsail/compose.yaml").resolve()
    print(
        "Offline IAM schema/syntax/managed-policy size, scope and reuse contracts "
        "validated. AWS authorization/Access Analyzer not_run."
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--kit"]:
        check_kit()
    else:
        if len(sys.argv) != 2:
            raise SystemExit("Usage: check-config.py --kit | PRIVATE_RUNTIME.env")
        # Retain exact private 0600/env/cost/consent guards, without evaluating shell.
        runpy.run_path(str(HERE / "../lightsail/check-config.py"), run_name="__main__")
