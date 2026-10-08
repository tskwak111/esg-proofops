"""Additive v2 mapping over the byte-preserved O1 composition and collections.

Acquisition is still v1: the same source PNG/model response is reused without
rewriting its trusted collection policy. Only the receipt's mapping is v2.
"""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import upstage_ocr_profile as v1
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_mapping_v2 import map_words as map_words
from proofops.adapters.local.upstage_ocr_mapping_v2 import mapping_sha256
from proofops.adapters.local.upstage_ocr_page import reader_policy as collection_policy
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v2"


def reader_policy():
    from proofops.adapters.local import upstage_ocr_mapping_v2 as mapping

    return dict(
        collection_policy(),
        profile=PROFILE,
        mapping_sha256=mapping_sha256(),
        mapping_reader_sha256=sha256(Path(mapping.__file__).read_bytes()).hexdigest(),
        collection_policy_sha256=canonical_hash(collection_policy()),
    )


def _policy(base):
    return dict(
        base,
        reader=reader_policy(),
        composition_sha256=sha256(Path(v1.__file__).read_bytes()).hexdigest(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def claim_source_policy():
    return _policy(dict(v1.claim_source_policy(), profile=PROFILE))


def native_policy():
    return _policy(dict(v1.native_policy(), mode=PROFILE))


def table_policy_sha256():
    from proofops.adapters.local.selected_cell_table_verification import policy_sha256

    return canonical_hash(dict(reader=native_policy(), selected_cell_policy=policy_sha256()))


def table_span_policy():
    return _policy(dict(v1.table_span_policy(), profile=PROFILE))


# Reuse the existing isolation pattern without editing any v1/frozen file or
# rebinding shared module globals. Every method resolves our private policies.
_composition = _exec_private(
    Path(__file__).parent,
    "upstage_ocr_profile.py",
    "proofops.adapters.local._ocr_v2_private.composition",
)
for _name in (
    "PROFILE",
    "map_words",
    "reader_policy",
    "claim_source_policy",
    "native_policy",
    "table_policy_sha256",
    "table_span_policy",
):
    setattr(_composition, _name, globals()[_name])

Reader = _composition.Reader
for_run = _composition.for_run
replay_claim_spans = _composition.replay_claim_spans


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    if run_id is None:
        raise ValueError("OCR_RUN_REQUIRED")
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def attest_tables(graph, source, *, tenant_id, run_id=None):
    if run_id is None:
        raise ValueError("OCR_RUN_REQUIRED")
    return for_run(run_id).attest_tables(graph, source, tenant_id=tenant_id)


def replay_tables(receipt, graph, source, *, tenant_id):
    return for_run(receipt["run_id"]).replay_tables(receipt, graph, source, tenant_id=tenant_id)
