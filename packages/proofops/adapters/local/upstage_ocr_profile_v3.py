"""O1c: existing rendered typography composed with existing glyph-space proof.

Native text/quotes stay literal. Only the five shipped Apple typography entries
can project OCR glyphs onto native spelling, and the unchanged glyph verifier
must then prove every deleted space. Projection without that proof grants no
approval. In particular U+25CF is NOT in the Apple table and stays unresolved.
The v2 mapping and immutable v1 provider collections are reused byte-for-byte.
"""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import claim_span_typography as typography
from proofops.adapters.local import glyph_alignment_verification as glyph
from proofops.adapters.local import upstage_ocr_profile as v1
from proofops.adapters.local import upstage_ocr_profile_v2 as v2
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v3"
map_words = v2.map_words


def normalization_policy():
    return dict(
        mode="existing_rendered_typography_then_existing_glyph_space_proof_v1",
        native_side_folded=False,
        rendered_fold_entries=[f"{s}->{t}" for s, t in typography._ADMITTED_ENTRIES],
        rendered_fold_sha256=canonical_hash(sorted(typography._RENDERED_FOLD.items())),
        typography_policy=typography.claim_source_policy(),
        glyph_policy=glyph.claim_source_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def reader_policy():
    return dict(
        v2.reader_policy(),
        profile=PROFILE,
        normalization_sha256=canonical_hash(normalization_policy()),
    )


def _policy(base):
    return dict(
        base,
        reader=reader_policy(),
        normalization=normalization_policy(),
        composition_sha256=sha256(Path(v1.__file__).read_bytes()).hexdigest(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def claim_source_policy():
    return _policy(dict(v2.claim_source_policy(), profile=PROFILE))


def native_policy():
    return _policy(dict(v2.native_policy(), mode=PROFILE))


def table_policy_sha256():
    from proofops.adapters.local.selected_cell_table_verification import policy_sha256

    return canonical_hash(dict(reader=native_policy(), selected_cell_policy=policy_sha256()))


def table_span_policy():
    return _policy(dict(v2.table_span_policy(), profile=PROFILE))


def align_reading(*, native, quote, reading, page_num, bbox, source_sha256):
    """Extend only freshly recomputed eligible readings; never mutate evidence.

    A space-insensitive walk is a veto/projection, never an admission gate.
    OCR spaces remain exactly where the OCR placed them. Native/quote codepoints
    and glyph indices never change, and the original line-local glyph proof
    alone determines which native joins may be deleted, with its same numeric,
    gap, local-control, containment, page and source constraints.
    """
    args = dict(
        native=native,
        quote=quote,
        reading=reading,
        page_num=page_num,
        bbox=bbox,
        source_sha256=source_sha256,
    )
    original = glyph.align_reading(**args)
    if original["status"] == "verified":
        return original
    rendered = reading.get("rendered", {})
    if (
        reading.get("reason") != "rendered_quote_unresolved"
        or rendered.get("status") != "read"
        or not glyph.strict._unique_quote(native, quote)
    ):
        return original
    text = " ".join(rendered.get("text", "").split())
    projected, substitutions = [], []
    native_offset = 0
    for offset, char in enumerate(text):
        if char == " ":
            projected.append(char)
            continue
        while native_offset < len(native) and native[native_offset] == " ":
            native_offset += 1
        if native_offset == len(native):
            return original
        target = native[native_offset]
        if char != target:
            if char.translate(typography._RENDERED_FOLD) != target.translate(
                typography._RENDERED_FOLD
            ):
                return original
            substitutions.append(
                dict(
                    rendered_offset=offset,
                    native_offset=native_offset,
                    rendered_char=char,
                    native_char=target,
                )
            )
        projected.append(target)
        native_offset += 1
    if native[native_offset:].strip() or not substitutions:
        return original
    projected_reading = deepcopy(reading)
    projected_reading["rendered"]["text"] = "".join(projected)
    result = glyph.align_reading(**dict(args, reading=projected_reading))
    if result["status"] != "verified":
        return result
    # Preserve the typography wrapper's two-sided folded uniqueness guard too.
    if not glyph.strict._unique_quote(
        typography._rendered_folded(text), typography._rendered_folded(result["aligned_quote"])
    ):
        return dict(status="unresolved", reason="rendered_folded_quote_not_unique")
    return dict(
        result,
        reason="existing_typography_and_glyph_proven_artificial_space",
        typography_substitutions=substitutions,
        native_side_folded=False,
        projected_rendered_read_sha256=result["rendered_read_sha256"],
        rendered_read_sha256=canonical_hash(rendered),
    )


_composition = _exec_private(
    Path(__file__).parent,
    "upstage_ocr_profile.py",
    "proofops.adapters.local._ocr_v3_private.composition",
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


# The byte-pinned exec module exposes Reader at runtime, outside mypy's AST.
class Reader(_composition.Reader):  # type: ignore[name-defined]
    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        modules["glyph_alignment_verification"].align_reading = align_reading
        return modules, seen


_composition.Reader = Reader
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
