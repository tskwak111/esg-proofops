from dataclasses import replace

import pytest
from proofops.application.reviews import ReviewRejected
from proofops.application.tagging.fact_assembly_c3 import PROFILE

from tests.integration.test_c2_receipt_lifecycle import inputs_for


@pytest.mark.parametrize("receipt", ["missing", "disabled_c2"])
def test_c3_profile_cannot_promote_missing_or_disabled_receipts(tmp_path, receipt):
    inputs = inputs_for(tmp_path)
    changed = replace(
        inputs,
        fact_assembly_profile=PROFILE,
        fact_assembly_receipt=None if receipt == "missing" else inputs.fact_assembly_receipt,
    )
    with pytest.raises(ReviewRejected, match="C3_PUBLICATION_REPLAY_MISMATCH"):
        changed.validate()


def test_original_a3_preview_keeps_pixel_bounds_and_default_renderer(tmp_path):
    from proofops.domain.documents import PageGeometry
    from proofops_api.hosted_page_render import render
    from proofops_api.hosted_store import HostedError
    from pypdf import PdfWriter

    source = tmp_path / "a3.pdf"
    writer = PdfWriter()
    writer.add_blank_page(841.92, 1191.12)
    writer.write(source)
    geometry = PageGeometry(841.92, 1191.12, 0, (0, 0, 841.92, 1191.12))
    with pytest.raises(HostedError, match="SOURCE_RENDER_UNAVAILABLE"):
        render(source, 1, geometry, tmp_path)
    png, metadata = render(source, 1, geometry, tmp_path, fit_page=True)
    assert png.startswith(b"\x89PNG")
    assert max(metadata["width_px"], metadata["height_px"]) <= 2000
    assert metadata["width_px"] * metadata["height_px"] <= 4_000_000
    assert 0 < metadata["dpi"] < 144
