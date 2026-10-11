"""Opt-in literal recovery. No new roles, source attestations or model votes."""

import re
from dataclasses import replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash

POLICY = dict(
    profile="local-hold-recovery-k2-v1",
    preliminary="unique-whitespace-only;ambiguous-dimension-null;retain-header",
    intrinsic_elements=["G1", "G2", "P1", "M1"],
    attribution="verified-single-atomic-span-only;no-cross-source-role-inference",
    missing_value="G1-G2-P1;one-literal-number-with-year-or-unit;never-replace-supplied-value",
    hold_display="actual-stop-or-unresolved-elements;no-document-absence-inference",
)
POLICY_HASH = canonical_hash(POLICY)


def validate_policy(policy):
    if policy != POLICY:
        raise ValueError("K2_RECOVERY_POLICY_MISMATCH")


def local_intrinsic(claim, ref, element_id):
    return (
        element_id in POLICY["intrinsic_elements"]
        and claim.source_quality == "verified"
        and len(claim.source_refs) == 1
        and claim.source_refs[0].source_id == ref.source_id
        and claim.source_refs[0].char_start
        <= ref.char_start
        < ref.char_end
        <= claim.source_refs[0].char_end
    )


_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNITS = (
    r"(?:%p?|MWh|kWh|GWh|MW|kW|GW|tCO[2₂](?:eq|e)?|kgCO[2₂](?:eq|e)?|"
    r"GJ|TJ|MJ|m[3³]|㎥|톤|kg|천tCO2eq|대)"
)
_VALUE = re.compile(r"(?<![\w.,])" + _NUMBER + r"\s*" + _UNITS + r"(?![A-Za-z0-9])")
_YEAR = re.compile(r"(?<![0-9])(?:19|20)[0-9]{2}년(?:까지)?")


def recover_value(element, refs, claim, graph, *, tenant_id):
    """Normalize only an already verified, uniquely quoted local scalar/year."""
    if element.normalized_value is not None or element.element_id not in {"G1", "G2", "P1"}:
        return element, refs
    if len(refs) != 1 or not local_intrinsic(claim, refs[0], element.element_id):
        return element, refs
    ref = refs[0]
    matches = list((_YEAR if element.element_id == "G1" else _VALUE).finditer(ref.quote))
    if len(matches) != 1:
        return element, refs
    match = matches[0]
    selected = replace(
        ref,
        quote=match[0],
        char_start=ref.char_start + match.start(),
        char_end=ref.char_start + match.end(),
        verification_state="candidate",
    )
    checked = verify_source_ref(selected, graph, tenant_id=tenant_id)
    if checked.verification_state != "verified":
        return element, refs
    return replace(element, normalized_value=checked.quote), [checked]
