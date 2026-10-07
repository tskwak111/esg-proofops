from copy import deepcopy

import pytest
from proofops.adapters.local.receipt_environment_compat import (
    ENVIRONMENT_FIELDS,
    PROFILE,
    compare_receipts,
)
from proofops.domain.provenance import canonical_hash


def receipt():
    value = dict(
        schema="native_merged_table_source_v2",
        policy_sha256="policy",
        input_graph_sha256="graph",
        records=[
            dict(
                cells=[
                    dict(
                        bbox=[1, 2, 3, 4],
                        rendered=dict(
                            status="read",
                            reader="Apple Vision",
                            os="old OS",
                            revision=3,
                            text="원문",
                            image_sha256="pixels",
                            pixel_bbox=[3, 6, 9, 12],
                        ),
                    )
                ]
            )
        ],
    )
    value["artifact_sha256"] = canonical_hash(value)
    return value


def changed(value):
    value = deepcopy(value)
    value["records"][0]["cells"][0]["rendered"]["os"] = "current OS"
    value["artifact_sha256"] = canonical_hash(
        {k: v for k, v in value.items() if k != "artifact_sha256"}
    )
    return value


def test_os_drift_and_immutable_input():
    saved = receipt()
    original = deepcopy(saved)
    meta = compare_receipts(saved, changed(saved), profile=PROFILE)
    assert ENVIRONMENT_FIELDS == frozenset({"os"})
    assert meta["read_profile"] == PROFILE
    assert meta["comparison_path"] == "environment_drift"
    assert meta["environment_drift"] == [
        dict(path="/records/0/cells/0/rendered/os", stored="old OS", current="current OS")
    ]
    assert saved == original
    with pytest.raises(ValueError):
        compare_receipts(saved, changed(saved))


@pytest.mark.parametrize(
    "field,new",
    [
        ("text", "原문"),
        ("image_sha256", "changed"),
        ("pixel_bbox", [3, 6, 9, 13]),
        ("revision", 4),
        ("compute", "gpu"),
    ],
)
def test_content_drift_rejected(field, new):
    saved = receipt()
    current = changed(saved)
    current["records"][0]["cells"][0]["rendered"][field] = new
    current["artifact_sha256"] = canonical_hash(
        {k: v for k, v in current.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError):
        compare_receipts(saved, current, profile=PROFILE)


@pytest.mark.parametrize(
    "mutation", ["policy", "graph", "bbox", "add", "delete", "os_delete", "hash", "os_elsewhere"]
)
def test_all_other_changes_rejected(mutation):
    saved = receipt()
    current = changed(saved)
    if mutation == "policy":
        current["policy_sha256"] = "other"
    elif mutation == "graph":
        current["input_graph_sha256"] = "other"
    elif mutation == "bbox":
        current["records"][0]["cells"][0]["bbox"][0] = 2
    elif mutation == "add":
        current["extra"] = None
    elif mutation == "delete":
        del current["schema"]
    elif mutation == "os_delete":
        del current["records"][0]["cells"][0]["rendered"]["os"]
    elif mutation == "os_elsewhere":
        saved["os"] = "old"
        current["os"] = "new"
    current["artifact_sha256"] = canonical_hash(
        {k: v for k, v in current.items() if k != "artifact_sha256"}
    )
    if mutation == "hash":
        current["artifact_sha256"] = "tampered"
    with pytest.raises(ValueError):
        compare_receipts(saved, current, profile=PROFILE)


def test_unknown_profile_and_exact_strict():
    saved = receipt()
    assert compare_receipts(saved, deepcopy(saved))["comparison_path"] == "strict"
    with pytest.raises(ValueError):
        compare_receipts(saved, saved, profile="unknown")


def test_table_metadata_is_bound_to_context_and_graph():
    from contextvars import Context
    from types import SimpleNamespace

    from proofops.adapters.local.receipt_environment_compat import (
        record_table_read,
        table_read_metadata,
    )

    saved = receipt()
    compare_receipts(saved, changed(saved), profile=PROFILE)
    # Explicit environment opt-in is the same selector used by durable reads.
    from unittest.mock import patch

    graph = SimpleNamespace(tenant_id="a", document_version_id="v", parse_manifest_id="p")
    foreign = SimpleNamespace(tenant_id="b", document_version_id="v", parse_manifest_id="p")
    with patch.dict("os.environ", {"PROOFOPS_RECEIPT_READ_PROFILE": PROFILE}):
        context = Context()
        context.run(record_table_read, saved, graph)
        assert context.run(table_read_metadata, graph)["environment_drift"]
        assert context.run(table_read_metadata, foreign) is None
        assert Context().run(table_read_metadata, graph) is None
