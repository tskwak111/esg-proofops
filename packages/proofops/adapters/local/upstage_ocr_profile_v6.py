"""HF1 opt-in extension of immutable v5: glyph-derived quote verification regions."""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import claim_source_glyph_region as region
from proofops.adapters.local import upstage_ocr_profile_v5 as v5
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v6"
PageOCRStore = v5.PageOCRStore


def map_words(words, manifest, box, *, competing_boxes=()):
    # The expanded region belongs to its glyph-proven, immutable parser owner.
    # Every other row/column remains a competing region.
    owner = region.VERIFICATION_OWNER.get()
    peers = [b for b in competing_boxes if owner is None or tuple(b) != owner]
    return v5.map_words(words, manifest, box, competing_boxes=peers)


def reader_policy():
    return dict(v5.reader_policy(), profile=PROFILE, glyph_region=region.policy())


def claim_source_policy():
    return dict(
        v5.claim_source_policy(),
        profile=PROFILE,
        reader=reader_policy(),
        glyph_region=region.policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    return dict(v5.native_policy(), mode=PROFILE, reader=reader_policy())


def table_policy_sha256():
    from proofops.adapters.local.selected_cell_table_verification import policy_sha256

    return canonical_hash(dict(reader=native_policy(), selected_cell_policy=policy_sha256()))


def table_span_policy():
    return dict(v5.table_span_policy(), profile=PROFILE, reader=reader_policy())


def _modules(base, filename, name):
    module = _exec_private(base, filename, name)
    if filename == "claim_source_verification_v3.py":
        original = module._recover
        # The extension retains the full v3 proof, using this same private reader.
        adapter = type("LiteralReader", (), {})()
        adapter._recover = original
        for attr in ("_canonical",):
            setattr(adapter, attr, getattr(module, attr))

        def recover(*args):
            # Original function globals retain module-local renderer injection.
            return region.recover(*args, literal=adapter)

        module._recover = recover
    return module


_wrapper = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v5.py", "proofops.adapters.local._ocr_v6"
)
_wrapper._exec_private = _modules
for _name in (
    "PROFILE",
    "map_words",
    "reader_policy",
    "claim_source_policy",
    "native_policy",
    "table_policy_sha256",
    "table_span_policy",
):
    setattr(_wrapper, _name, globals()[_name])
    setattr(_wrapper._composition, _name, globals()[_name])
Reader = _wrapper.Reader
for_run = _wrapper.for_run
replay_claim_spans = _wrapper.replay_claim_spans
attest_claim_spans = _wrapper.attest_claim_spans
attest_tables = _wrapper.attest_tables
replay_tables = _wrapper.replay_tables
