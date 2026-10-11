"""I4 partial P2 adoption on frozen v3 guidance; no extraction/admission changes.

COMMON/track/TAIL renderer and strict K4 schema guard adapted from P2 80942eb.
The reconstructed P2 extraction and full rubric systems are not selected.
"""

import re
from pathlib import Path

from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

PROFILE = "finals-20261012-v4-partial"
_ASSETS = Path(__file__).with_name("finals_i4_assets")
K4_PRELIMINARY = (_ASSETS / "preliminary_identity.md").read_text().strip()
K4_ELEMENTS = (_ASSETS / "elements_partial.md").read_text().strip()
POLICY = dict(
    profile=PROFILE,
    preliminary_sha256=canonical_hash(K4_PRELIMINARY),
    elements_sha256=canonical_hash(K4_ELEMENTS),
    renderer="common-track-tail-k4-v1",
    adoption="v3-guidance; identity-free; P2-normalized-values-and-G6-only",
    max_request_bytes=16384,
)


def _require_k4_schema(schema):
    fields = {"claim_id", "packet_sha256", "replicate_id"}
    if fields & (set(schema.get("properties", {})) | set(schema.get("required", []))):
        raise ValueError("K4_WIRE_SCHEMA_IDENTITY_PROHIBITED")
    if schema.get("additionalProperties") is not False:
        raise ValueError("K4_WIRE_SCHEMA_EXTRA_PROPERTIES_PROHIBITED")


def preliminary_k4(schema):
    _require_k4_schema(schema)
    return K4_PRELIMINARY.replace("{{OUTPUT_SCHEMA_JSON}}", canonical_json(schema))


def elements_k4(schema, classification):
    _require_k4_schema(schema)
    track = classification.get("track")
    if track not in ("goal", "performance", "management"):
        raise ValueError("I4_TRACK_INVALID")
    parts = []
    for section in ("COMMON", track, "TAIL"):
        match = re.search(
            rf"<!-- BEGIN {section} -->\n(.*?)\n<!-- END {section} -->", K4_ELEMENTS, re.S
        )
        if match is None:
            raise ValueError("I4_TEMPLATE_INVALID")
        parts.append(match.group(1).strip())
    return (
        "\n\n".join(parts)
        .replace("{{OUTPUT_SCHEMA_JSON}}", canonical_json(schema))
        .replace("{{CLASSIFICATION_JSON}}", canonical_json(classification))
    )
