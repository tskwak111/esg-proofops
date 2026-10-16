"""HX3 item-local source holds; v15 and all prior receipts retain their exact code."""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import evidence_source_hx3 as evidence
from proofops.adapters.local import source_hx3
from proofops.adapters.local import upstage_ocr_profile_v15 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v16"


def claim_source_policy():
    return dict(
        previous.claim_source_policy(),
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        evidence_policy=evidence.policy(),
        item_holds=source_hx3.policy(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    return dict(previous.native_policy(), mode=PROFILE, hx3=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(dict(previous=previous.table_policy_sha256(), hx3=native_policy()))


def table_span_policy():
    return dict(previous.table_span_policy(), profile=PROFILE, hx3=claim_source_policy())


# Private module binding keeps every byte-pinned historical global unchanged.
_reader = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v15.py", "proofops.adapters.local._hx3_source"
)
_reader.PROFILE = PROFILE
_reader.evidence = evidence
_reader.claim_source_policy = claim_source_policy
_reader.native_policy = native_policy
_reader.table_policy_sha256 = table_policy_sha256
_reader.table_span_policy = table_span_policy
PageOCRStore = _reader.PageOCRStore


class Reader(_reader.Reader):
    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        for module in modules.values():
            for name in ("_rendered_text", "_rendered_cell"):
                if hasattr(module, name):
                    setattr(module, name, source_hx3.hold_read(getattr(module, name)))
        return modules, seen


_reader.Reader = Reader
for_run = _reader.for_run
attest_claim_spans = _reader.attest_claim_spans
attest_tables = _reader.attest_tables
replay_tables = _reader.replay_tables
replay_claim_spans = _reader.replay_claim_spans
