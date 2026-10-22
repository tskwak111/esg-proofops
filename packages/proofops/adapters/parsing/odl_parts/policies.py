"""Existing local-page and immutable table-reader selection."""

from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES
from proofops.adapters.parsing.odl_parts.common import ParseFailure


def _table_verifier(policy_hash):
    from proofops.adapters.local import table_source_verification as legacy

    if policy_hash == legacy.policy_sha256():
        return legacy
    from proofops.adapters.local import merged_table_verification as merged

    if policy_hash == merged.policy_sha256():
        return merged
    from proofops.adapters.local import selected_cell_table_verification as selected

    if policy_hash == selected.policy_sha256():
        return selected
    from proofops.adapters.local.claim_source_policies import page_ocr_profile

    for name in PAGE_OCR_PROFILES:
        profile = page_ocr_profile(name)
        if policy_hash == profile.table_policy_sha256():
            return profile
    raise ParseFailure("TABLE_SOURCE_POLICY_MISMATCH")


def _locates_auxiliary_cells(profile):
    """Only the selected-cell policy asks for ink-tight auxiliary cell boxes.

    Pinning that policy in the parser profile IS the new source version: existing
    runs keep their own policy and their artifacts are never rewritten.
    """
    policy_hash = (
        profile.get("table_source_policy_sha256")
        if isinstance(profile, dict)
        else profile.table_source_policy_sha256
    )
    if policy_hash is None:
        return False
    from proofops.adapters.parsing import spp_execution

    if spp_execution.enabled(profile):
        spp_execution.table_verifier(policy_hash)
        return True
    from proofops.adapters.local import selected_cell_table_verification as selected
    from proofops.adapters.local.claim_source_policies import page_ocr_profile

    return policy_hash in {
        selected.policy_sha256(),
        *(page_ocr_profile(name).table_policy_sha256() for name in PAGE_OCR_PROFILES),
    }


def _local_pages(profile):
    from proofops.adapters.parsing import h6_local_pages, h6_local_pages_v2

    resource = (
        profile.get("local_resource_policy")
        if isinstance(profile, dict)
        else profile.local_resource_policy
    )
    return h6_local_pages_v2 if resource == "selected-pdf-h6-v2" else h6_local_pages
