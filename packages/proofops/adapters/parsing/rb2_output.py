"""Lossless, bounded candidate-artifact compaction for RB2's explicit pin.

Only an otherwise oversized artifact set uses this representation. The parser's
20 MB ceiling is unchanged, and expanded candidate bytes have that same ceiling.
All candidate nodes and original references survive; this is not evidence repair.
"""

import gzip
import io
import json
import zlib
from hashlib import sha256

PROFILE = "rb2-output-v1"
ARTIFACT = "rb2-candidates.json.gz"
GRAPH_ARTIFACT = "rb2-graph.json.gz"


def compact(work, profile, *, manifest_bytes):
    from proofops.adapters.parsing.opendataloader import _output_bytes

    if _output_bytes(work) + manifest_bytes <= profile.max_output_bytes:
        return None
    receipt = _compress(work / "candidates.json", work / ARTIFACT, profile)
    if receipt is None:
        return None
    # Korea Zinc's graph plus other artifacts alone exceeds 20 MB even after
    # candidate compression. Compact that exact graph too, only when necessary.
    if _output_bytes(work) + manifest_bytes + len(json.dumps(receipt)) + 128 > (
        profile.max_output_bytes
    ):
        graph_receipt = _compress(work / "graph.json", work / GRAPH_ARTIFACT, profile)
        if graph_receipt is not None:
            receipt["graph"] = graph_receipt
    return receipt


def _compress(source, target, profile):
    from proofops.adapters.parsing.opendataloader import ParseFailure

    size = source.stat().st_size
    if size > profile.max_output_bytes:
        raise ParseFailure("PARSER_OUTPUT_LIMIT")
    digest = sha256()
    with source.open("rb") as incoming, target.open("wb") as outgoing:
        with gzip.GzipFile(filename="", mode="wb", fileobj=outgoing, mtime=0) as compressed:
            while chunk := incoming.read(65536):
                digest.update(chunk)
                compressed.write(chunk)
    # Incompressible input must not grow the retained artifact set.
    if target.stat().st_size >= size:
        target.unlink()
        return None
    source.unlink()
    return dict(profile=PROFILE, original_bytes=size, sha256=digest.hexdigest())


def read_candidates(data, profile, receipt):
    """Never trust a compressed length or decompress an unbounded provider blob."""
    limit = profile.max_output_bytes
    if not isinstance(receipt, dict):
        raise ValueError("RB2_CANDIDATE_RECEIPT")
    size = receipt.get("original_bytes")
    if (
        profile.output_policy != PROFILE
        or receipt.get("profile") != PROFILE
        or type(size) is not int
        or not 0 < size <= limit
        or len(data) > limit
    ):
        raise ValueError("RB2_CANDIDATE_LIMIT")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as compressed:
            expanded = compressed.read(size + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError("RB2_CANDIDATE_ENCODING") from error
    if len(expanded) != size or sha256(expanded).hexdigest() != receipt.get("sha256"):
        raise ValueError("RB2_CANDIDATE_INTEGRITY")
    return json.loads(expanded)
