"""Read manifest-pinned parser JSON in either retained storage representation.

Callers retain their tenant/source/manifest anchors. These helpers verify the
stored artifact hash and RB2's bounded original-byte commitment, without
rewriting artifacts or treating decompression as source verification.
"""

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from proofops.adapters.parsing.rb2_output import ARTIFACT, GRAPH_ARTIFACT, read_candidates

_COMPRESSED = {"candidates.json": ARTIFACT, "graph.json": GRAPH_ARTIFACT}
_LOGICAL = {v: k for k, v in _COMPRESSED.items()}
_LIMIT = 20_000_000


def _managed(path, manifest):
    return manifest is not None or (
        path.name in _COMPRESSED | _LOGICAL and path.with_name("manifest.json").exists()
    )


def _bytes(path, limit):
    if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > limit:
        raise ValueError("PARSER_ARTIFACT_UNSAFE")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("PARSER_ARTIFACT_LIMIT")
    return data


def _manifest(path, manifest):
    if manifest is None:
        manifest = json.loads(_bytes(path.with_name("manifest.json"), _LIMIT))
    if not isinstance(manifest, dict):
        raise ValueError("PARSER_ARTIFACT_MANIFEST")
    return manifest


def parser_artifact_path(path, *, manifest=None):
    """Resolve a logical name; returned names are the manifest's physical files."""
    path = Path(path)
    if not _managed(path, manifest):
        if path.name in _LOGICAL:
            raise ValueError("PARSER_ARTIFACT_MANIFEST")
        return path
    manifest = _manifest(path, manifest)
    logical = _LOGICAL.get(path.name, path.name)
    receipt = manifest.get("rb2_output")
    if receipt is not None and not isinstance(receipt, dict):
        raise ValueError("RB2_CANDIDATE_RECEIPT")
    compressed = receipt is not None and (
        logical == "candidates.json" or (logical == "graph.json" and receipt.get("graph"))
    )
    name = _COMPRESSED[logical] if compressed else logical
    artifacts = manifest["artifacts"]
    if name not in artifacts or (compressed and logical in artifacts):
        raise ValueError("PARSER_ARTIFACT_MANIFEST")
    if path.name not in (logical, name):
        raise ValueError("PARSER_ARTIFACT_REPRESENTATION")
    return path.with_name(name)


def read_parser_json(path, *, manifest=None):
    """Plain fixture catalogs remain plain JSON; parser artifacts are checked.

    A caller with an anchored manifest must supply it. Compacted artifacts never
    fall back to an unchecked read when their manifest is absent.
    """
    path = Path(path)
    if not _managed(path, manifest):
        if path.name in _LOGICAL:
            raise ValueError("PARSER_ARTIFACT_MANIFEST")
        return json.loads(path.read_bytes())
    manifest = _manifest(path, manifest)
    actual = parser_artifact_path(path, manifest=manifest)
    settings = manifest.get("parser_profile", {})
    limit = settings.get("max_output_bytes", _LIMIT)
    if type(limit) is not int or not 0 < limit <= _LIMIT:
        raise ValueError("PARSER_ARTIFACT_LIMIT")
    data = _bytes(actual, limit)
    if sha256(data).hexdigest() != manifest["artifacts"][actual.name]:
        raise ValueError("PARSER_ARTIFACT_INTEGRITY")
    if actual.name in _LOGICAL:
        receipt = manifest["rb2_output"]
        if actual.name == GRAPH_ARTIFACT:
            receipt = receipt["graph"]
        profile = SimpleNamespace(
            max_output_bytes=limit, output_policy=settings.get("output_policy")
        )
        return read_candidates(data, profile, receipt)
    return json.loads(data)


def iter_parser_artifacts(root, name):
    """Discover raw or compacted artifacts without silently dropping either."""
    yield from Path(root).rglob(name)
    if name in _COMPRESSED:
        yield from Path(root).rglob(_COMPRESSED[name])
