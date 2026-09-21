"""Offline preparation of review candidates from pinned DART originals.

The adapter deliberately produces *candidates*, never reviewed facts, search
receipts, accounting mappings, policy approvals, or reconciliation outcomes.
Every usable source points either at original XML bytes by a unique element ID
or at an explicitly derived UTF-8 text projection with complete parent lineage.
"""

from __future__ import annotations

import codecs
import copy
import hashlib
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from proofops.adapters.dart.artifacts import ArtifactStore, safe_parse_xml
from proofops.adapters.dart.normalization import normalize_financial_amount
from proofops.adapters.reconciliation import FileSourceReader

CATALOG_SCHEMA = "reconciliation-candidates-1"
MAX_CANDIDATES = 2_000
MAX_QUOTE_CHARS = 8_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CORP = re.compile(r"^[0-9]{8}$")
_RECEIPT = re.compile(r"^[0-9]{14}$")
_XML_DECL_ENCODING = re.compile(rb"<\?xml[^>]+encoding=['\"]\s*([^'\"\s]+)", re.I)


class CandidatePreparationError(ValueError):
    """A collection cannot be safely converted into review candidates."""


@dataclass(frozen=True, slots=True)
class CandidateArtifact:
    """Bytes destined for the bounded review artifact directory."""

    document_id: str
    path: str
    format: str
    sha256: str
    payload: bytes
    lineage: dict[str, Any]

    def index_entry(self) -> dict[str, str]:
        return {"path": self.path, "format": self.format, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class PreparedCandidates:
    catalog: dict[str, Any]
    artifacts: tuple[CandidateArtifact, ...]

    @property
    def artifact_index(self) -> dict[str, dict[str, str]]:
        return {artifact.document_id: artifact.index_entry() for artifact in self.artifacts}


def add_operator_sr_sources(
    prepared: PreparedCandidates,
    manifest: Mapping[str, Any],
    root: str | Path,
    *,
    max_sources: int = 100,
) -> PreparedCandidates:
    """Add bounded, byte-verified sustainability-report source candidates.

    ``root`` is operator-controlled local input.  Every path remains constrained
    by ``FileSourceReader`` and every source locator/quote is validated before
    bytes are copied to the prepared output.
    """
    if (
        type(max_sources) is not int
        or not 1 <= max_sources <= MAX_CANDIDATES
        or not isinstance(manifest, Mapping)
        or set(manifest) != {"schema_version", "artifacts", "documents", "sources"}
        or manifest.get("schema_version") != "reconciliation-sr-sources-1"
        or not isinstance(manifest.get("artifacts"), Mapping)
        or not isinstance(manifest.get("documents"), Mapping)
        or not isinstance(manifest.get("sources"), list)
        or not 1 <= len(manifest["sources"]) <= max_sources
    ):
        raise CandidatePreparationError("sr_source_manifest_invalid")
    try:
        reader = FileSourceReader(root, manifest["artifacts"])
    except ValueError as exc:
        raise CandidatePreparationError("sr_artifact_index_invalid") from exc
    documents = copy.deepcopy(dict(manifest["documents"]))
    if set(documents) != set(manifest["artifacts"]):
        raise CandidatePreparationError("sr_document_index_mismatch")
    artifacts = {artifact.document_id: artifact for artifact in prepared.artifacts}
    candidates = list(prepared.catalog["candidates"])
    seen_sources: set[str] = set()
    for source in manifest["sources"]:
        if not isinstance(source, Mapping) or set(source) != {
            "source_id",
            "document_id",
            "artifact_sha256",
            "locator",
            "quote",
            "lineage",
        }:
            raise CandidatePreparationError("sr_source_invalid")
        source_id, document_id = source.get("source_id"), source.get("document_id")
        lineage = source.get("lineage")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in seen_sources
            or not isinstance(document_id, str)
            or document_id not in documents
            or not isinstance(lineage, Mapping)
            or lineage.get("representation") not in {"original", "derived"}
            or not isinstance(lineage.get("original_artifact_sha256"), str)
            or _SHA256.fullmatch(lineage["original_artifact_sha256"]) is None
            or not isinstance(lineage.get("transformation"), str)
            or not lineage["transformation"]
            or not isinstance(lineage.get("transformation_locator"), str)
            or not lineage["transformation_locator"]
        ):
            raise CandidatePreparationError("sr_source_or_lineage_invalid")
        if lineage["representation"] == "original" and (
            lineage["original_artifact_sha256"] != source.get("artifact_sha256")
            or lineage["transformation"] != "none"
        ):
            raise CandidatePreparationError("sr_original_lineage_invalid")
        if lineage["representation"] == "derived":
            original_path = lineage.get("original_path")
            if (
                not isinstance(original_path, str)
                or not original_path
                or ":" in original_path
                or Path(original_path).is_absolute()
            ):
                raise CandidatePreparationError("sr_derived_parent_invalid")
            root_path = Path(root).resolve(strict=True)
            try:
                parent = (root_path / original_path).resolve(strict=True)
                if not parent.is_relative_to(root_path) or not parent.is_file():
                    raise CandidatePreparationError("sr_derived_parent_invalid")
                if parent.stat().st_size > 50 * 1024 * 1024:
                    raise CandidatePreparationError("sr_derived_parent_invalid")
                parent_payload = parent.read_bytes()
            except OSError as exc:
                raise CandidatePreparationError("sr_derived_parent_invalid") from exc
            if _digest(parent_payload) != lineage["original_artifact_sha256"]:
                raise CandidatePreparationError("sr_derived_parent_hash_mismatch")
        try:
            payload = reader(source)
            reader.validate(source, payload)
        except ValueError as exc:
            raise CandidatePreparationError("sr_source_verification_failed") from exc
        artifact_spec = manifest["artifacts"][document_id]
        format_name = artifact_spec["format"]
        extension = {"text": ".txt", "xml": ".xml", "html": ".html", "pdf": ".pdf"}[format_name]
        artifact = CandidateArtifact(
            document_id=document_id,
            path=f"operator/{source['artifact_sha256']}{extension}",
            format=format_name,
            sha256=source["artifact_sha256"],
            payload=payload,
            lineage=dict(lineage),
        )
        previous = artifacts.get(document_id)
        if previous is not None and previous.sha256 != artifact.sha256:
            raise CandidatePreparationError("sr_document_artifact_conflict")
        artifacts[document_id] = artifact
        raw = {"quote": source["quote"], "document_role": "sustainability"}
        candidate_lineage = {
            **dict(lineage),
            "source_locator": source["locator"],
        }
        candidate = {
            "candidate_type": "sustainability_source",
            "verification_state": "candidate",
            "source": {
                key: source[key]
                for key in (
                    "source_id",
                    "document_id",
                    "artifact_sha256",
                    "locator",
                    "quote",
                )
            }
            | {"format": format_name},
            "lineage": candidate_lineage,
            "raw": raw,
            "normalization_suggestions": {},
        }
        candidate["candidate_id"] = _candidate_id(candidate_lineage, raw)
        candidates.append(candidate)
        seen_sources.add(source_id)
    catalog = copy.deepcopy(prepared.catalog)
    catalog["candidates"] = candidates
    catalog["artifacts"] = [
        {"document_id": item.document_id, **item.index_entry(), "lineage": item.lineage}
        for item in sorted(artifacts.values(), key=lambda value: value.document_id)
    ]
    catalog["operator_documents"] = documents
    return PreparedCandidates(
        catalog=catalog,
        artifacts=tuple(sorted(artifacts.values(), key=lambda value: value.document_id)),
    )


class _DartTextProjectionParser(HTMLParser):
    """Tolerant text reader for DART's non-well-formed proprietary markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.rows: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append(tag)

    def handle_startendtag(self, _tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[index:]

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.rows.append(("/" + "/".join(self.stack or ["document"]), text))


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidatePreparationError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise CandidatePreparationError("non_finite_json_number")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidatePreparationError("non_canonical_value") from exc


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _strict_xml_decode(payload: bytes) -> str:
    """Prove that XML is losslessly decodable before ElementTree sees it."""
    if payload.startswith(b"\x00\x00\xfe\xff"):
        encoding = "utf-32-be"
    elif payload.startswith(b"\xff\xfe\x00\x00"):
        encoding = "utf-32-le"
    elif payload.startswith(b"\xfe\xff"):
        encoding = "utf-16-be"
    elif payload.startswith(b"\xff\xfe"):
        encoding = "utf-16-le"
    else:
        match = _XML_DECL_ENCODING.search(payload[:512])
        if match:
            try:
                encoding = match.group(1).decode("ascii")
                codecs.lookup(encoding)
            except (UnicodeDecodeError, LookupError) as exc:
                raise CandidatePreparationError("xml_encoding_unknown") from exc
        elif b"\x00" in payload[:8]:
            raise CandidatePreparationError("xml_encoding_unknown")
        else:
            encoding = "utf-8"
    try:
        return payload.decode(encoding, errors="strict")
    except UnicodeError as exc:
        raise CandidatePreparationError("xml_encoding_unreadable") from exc


def _artifact_kind(source_id: str, locator: str) -> str:
    suffix = Path(locator).suffix.lower()
    if source_id.endswith(":statements") and suffix == ".json":
        return "statements"
    if source_id.endswith(":document") and suffix == ".zip":
        return "document"
    if source_id.endswith(":xbrl") and suffix == ".zip":
        return "xbrl"
    raise CandidatePreparationError("artifact_kind_or_extension_invalid")


def _validated_originals(
    manifest: Mapping[str, Any],
    store: ArtifactStore,
    *,
    corp_code: str,
    fy: int,
    rcept_no: str,
    consolidation: str,
) -> list[tuple[str, Mapping[str, Any], bytes]]:
    if (
        not isinstance(manifest, Mapping)
        or set(manifest)
        != {
            "schema_version",
            "manifest_id",
            "package_id",
            "synthetic",
            "fetched_at",
            "artifacts",
        }
        or manifest.get("schema_version") != "collection-1"
        or not isinstance(manifest.get("manifest_id"), str)
        or not manifest.get("manifest_id")
        or not isinstance(manifest.get("package_id"), str)
        or not manifest.get("package_id")
        or type(manifest.get("synthetic")) is not bool
        or not isinstance(manifest.get("artifacts"), list)
        or not manifest["artifacts"]
    ):
        raise CandidatePreparationError("collection_schema_invalid")
    if (
        _CORP.fullmatch(corp_code) is None
        or type(fy) is not int
        or not 1900 <= fy <= 2200
        or _RECEIPT.fullmatch(rcept_no) is None
        or consolidation not in {"consolidated", "separate"}
    ):
        raise CandidatePreparationError("expected_identity_invalid")

    required = {
        "source_id",
        "document_version_id",
        "artifact_sha256",
        "corp_code",
        "fy",
        "rcept_no",
        "consolidation",
        "source_system",
        "locator",
        "status",
        "error_code",
        "fetched_at",
    }
    seen: set[str] = set()
    originals: list[tuple[str, Mapping[str, Any], bytes]] = []
    for entry in manifest["artifacts"]:
        if not isinstance(entry, Mapping) or set(entry) != required:
            raise CandidatePreparationError("collection_artifact_schema_invalid")
        source_id = entry.get("source_id")
        digest = entry.get("artifact_sha256")
        locator = entry.get("locator")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in seen
            or entry.get("status") != "retrieved"
            or entry.get("error_code") is not None
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or not isinstance(locator, str)
            or not locator
            or entry.get("source_system") != "DART"
            or entry.get("corp_code") != corp_code
            or entry.get("fy") != fy
            or entry.get("rcept_no") != rcept_no
            or entry.get("consolidation") != consolidation
        ):
            raise CandidatePreparationError("collection_identity_or_status_mismatch")
        kind = _artifact_kind(source_id, locator)
        extension = Path(locator).suffix
        expected_path = store.path_for(digest, ext=extension).relative_to(store.root).as_posix()
        if locator != expected_path:
            raise CandidatePreparationError("artifact_locator_mismatch")
        try:
            payload = store.get(digest, ext=extension)
        except (OSError, ValueError) as exc:
            raise CandidatePreparationError("artifact_hash_or_read_failure") from exc
        seen.add(source_id)
        originals.append((kind, entry, payload))
    if set(kind for kind, _entry, _payload in originals) != {"statements", "document", "xbrl"}:
        raise CandidatePreparationError("required_artifact_set_missing")
    return originals


def _candidate_id(lineage: Mapping[str, Any], raw: Mapping[str, Any] | str) -> str:
    return "cand-" + _digest(_canonical({"lineage": lineage, "raw": raw}))[:24]


def _projection_artifact(
    *,
    document_id: str,
    payload: bytes,
    parent_entry: Mapping[str, Any],
    zip_member: str | None,
    member_sha256: str | None,
    transformation: str,
) -> CandidateArtifact:
    digest = _digest(payload)
    return CandidateArtifact(
        document_id=document_id,
        path=f"derived/{digest}.txt",
        format="text",
        sha256=digest,
        payload=payload,
        lineage={
            "representation": "derived",
            "original_source_id": parent_entry["source_id"],
            "original_artifact_sha256": parent_entry["artifact_sha256"],
            "zip_member": zip_member,
            "member_sha256": member_sha256,
            "transformation": transformation,
        },
    )


def _source(
    artifact: CandidateArtifact, source_id: str, locator: str, quote: str
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "document_id": artifact.document_id,
        "artifact_sha256": artifact.sha256,
        "format": artifact.format,
        "locator": locator,
        "quote": quote,
    }


def _statement_candidates(
    entry: Mapping[str, Any], payload: bytes, *, corp_code: str, fy: int, rcept_no: str
) -> tuple[list[dict[str, Any]], CandidateArtifact]:
    try:
        parsed = json.loads(
            payload.decode("utf-8-sig", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CandidatePreparationError("statements_json_invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("status") != "000":
        raise CandidatePreparationError("statements_status_invalid")
    rows = parsed.get("list")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise CandidatePreparationError("statements_rows_invalid")

    lines: list[str] = []
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for row in rows:
        if (
            row.get("corp_code") != corp_code
            or row.get("bsns_year") != str(fy)
            or row.get("rcept_no") != rcept_no
        ):
            raise CandidatePreparationError("statement_row_identity_mismatch")
        line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(line)
        ranges.append((cursor, cursor + len(line)))
        cursor += len(line) + 1
    projection = ("\n".join(lines) + "\n").encode("utf-8")
    artifact = _projection_artifact(
        document_id=f"{entry['document_version_id']}:statements-projection",
        payload=projection,
        parent_entry=entry,
        zip_member=None,
        member_sha256=None,
        transformation="dart-statements-json/list-row -> canonical-key-order UTF-8 JSONL",
    )
    candidates: list[dict[str, Any]] = []
    for index, (row, line, (start, end)) in enumerate(zip(rows, lines, ranges, strict=True)):
        lineage = {
            **artifact.lineage,
            "transformation_locator": f"/list/{index}",
            "derived_locator": f"chars:{start}:{end}",
        }
        suggestions: dict[str, Any] = {}
        for prefix in ("thstrm", "frmtrm", "bfefrmtrm"):
            amount = row.get(f"{prefix}_amount")
            if isinstance(amount, str | int) and not isinstance(amount, bool):
                try:
                    suggestions[prefix] = normalize_financial_amount(
                        amount, currency=str(row.get("currency") or "KRW"), unit_raw=""
                    )
                except ValueError:
                    pass
        candidate: dict[str, Any] = {
            "candidate_type": "statement_row",
            "verification_state": "candidate",
            "source": _source(
                artifact,
                f"{entry['source_id']}:row:{index}",
                lineage["derived_locator"],
                line,
            ),
            "lineage": lineage,
            "raw": {
                key: copy.deepcopy(row.get(key))
                for key in (
                    "rcept_no",
                    "reprt_code",
                    "bsns_year",
                    "corp_code",
                    "sj_div",
                    "sj_nm",
                    "account_id",
                    "account_nm",
                    "account_detail",
                    "thstrm_nm",
                    "thstrm_amount",
                    "frmtrm_nm",
                    "frmtrm_amount",
                    "bfefrmtrm_nm",
                    "bfefrmtrm_amount",
                    "ord",
                    "currency",
                )
            },
            "normalization_suggestions": suggestions,
        }
        candidate["candidate_id"] = _candidate_id(lineage, candidate["raw"])
        candidates.append(candidate)
    return candidates, artifact


def _element_path(root: Any, target: Any) -> str:
    found: list[str] | None = None

    def walk(node: Any, parts: list[str]) -> None:
        nonlocal found
        if found is not None:
            return
        if node is target:
            found = parts
            return
        counts: Counter[str] = Counter()
        for child in list(node):
            name = _local_name(child.tag)
            counts[name] += 1
            walk(child, [*parts, f"{name}[{counts[name]}]"])

    walk(root, [f"{_local_name(root.tag)}[1]"])
    return "/" + "/".join(found or ["unknown[1]"])


def _proprietary_member_candidates(
    entry: Mapping[str, Any],
    member_name: str,
    member: bytes,
    decoded: str,
    *,
    candidate_limit: int,
) -> tuple[list[dict[str, Any]], list[CandidateArtifact]]:
    lowered = decoded.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise CandidatePreparationError("xml_parse_rejected")
    parser = _DartTextProjectionParser()
    try:
        parser.feed(decoded)
        parser.close()
    except (ValueError, RecursionError) as exc:
        raise CandidatePreparationError("xml_parse_rejected") from exc
    rows = [(path, text) for path, text in parser.rows if len(text) <= MAX_QUOTE_CHARS][
        :candidate_limit
    ]
    if not rows:
        return [], []
    lines: list[str] = []
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for path, text in rows:
        line = f"{path}\t{text}"
        lines.append(line)
        ranges.append((cursor, cursor + len(line)))
        cursor += len(line) + 1
    member_hash = _digest(member)
    artifact = _projection_artifact(
        document_id=f"{entry['document_version_id']}:document:{member_hash[:16]}:projection",
        payload=("\n".join(lines) + "\n").encode("utf-8"),
        parent_entry=entry,
        zip_member=member_name,
        member_sha256=member_hash,
        transformation=(
            "DART proprietary markup HTMLParser text-node extraction, "
            "character-reference decode and whitespace-collapse -> path-tab-text UTF-8 projection"
        ),
    )
    candidates: list[dict[str, Any]] = []
    for index, ((path, text), line, (start, end)) in enumerate(
        zip(rows, lines, ranges, strict=True)
    ):
        locator = f"chars:{start}:{end}"
        lineage = {
            **artifact.lineage,
            "transformation_locator": f"proprietary-markup-text-node:{index}:{path}",
            "derived_locator": locator,
        }
        raw = {"element_path": path, "text": text}
        candidate = {
            "candidate_type": "document_element",
            "verification_state": "candidate",
            "source": _source(
                artifact,
                f"{entry['source_id']}:{member_hash[:12]}:{index}",
                locator,
                line,
            ),
            "lineage": lineage,
            "raw": raw,
            "normalization_suggestions": {},
        }
        candidate["candidate_id"] = _candidate_id(lineage, raw)
        candidates.append(candidate)
    return candidates, [artifact]


def _xml_member_candidates(
    entry: Mapping[str, Any],
    member_name: str,
    member: bytes,
    *,
    kind: str,
    candidate_limit: int,
) -> tuple[list[dict[str, Any]], list[CandidateArtifact]]:
    decoded = _strict_xml_decode(member)
    try:
        root = safe_parse_xml(member)
    except (ET.ParseError, LookupError, ValueError) as exc:
        if kind == "document":
            return _proprietary_member_candidates(
                entry,
                member_name,
                member,
                decoded,
                candidate_limit=candidate_limit,
            )
        raise CandidatePreparationError("xml_parse_rejected") from exc
    member_hash = _digest(member)
    id_values = [
        value
        for element in root.iter()
        for key, value in element.attrib.items()
        if _local_name(key).lower() == "id" and isinstance(value, str) and value
    ]
    id_counts = Counter(id_values)
    usable: list[tuple[Any, str, str, str | None]] = []
    for element in root.iter():
        literal_text = "".join(element.itertext()).strip()
        text = " ".join(literal_text.split())
        if not text or len(text) > MAX_QUOTE_CHARS:
            continue
        element_id = next(
            (
                value
                for key, value in element.attrib.items()
                if _local_name(key).lower() == "id" and id_counts[value] == 1
            ),
            None,
        )
        # Narrative XML: leaf-like text blocks. XBRL: facts with contextRef.
        if kind == "xbrl":
            if not any(_local_name(k).lower() == "contextref" for k in element.attrib):
                continue
        elif list(element) and len(text) > 2_000:
            continue
        usable.append((element, text, literal_text, element_id))
        if len(usable) == candidate_limit:
            break

    artifacts: list[CandidateArtifact] = []
    original_artifact: CandidateArtifact | None = None
    derived_rows: list[tuple[Any, str, str, int, int]] = []
    cursor = 0
    for element, text, _literal_text, element_id in usable:
        if element_id is None:
            path = _element_path(root, element)
            line = f"{path}\t{text}"
            derived_rows.append((element, text, path, cursor, cursor + len(line)))
            cursor += len(line) + 1
    derived_artifact: CandidateArtifact | None = None
    if derived_rows:
        projection = (
            "\n".join(f"{path}\t{text}" for _, text, path, _, _ in derived_rows) + "\n"
        ).encode("utf-8")
        derived_artifact = _projection_artifact(
            document_id=f"{entry['document_version_id']}:{kind}:{member_hash[:16]}:projection",
            payload=projection,
            parent_entry=entry,
            zip_member=member_name,
            member_sha256=member_hash,
            transformation="XML itertext whitespace-collapse -> path-tab-text UTF-8 projection",
        )
        artifacts.append(derived_artifact)
    if any(element_id is not None for _, _, _, element_id in usable):
        original_artifact = CandidateArtifact(
            document_id=f"{entry['document_version_id']}:{kind}:{member_hash[:16]}",
            path=f"members/{member_hash}{Path(member_name).suffix.lower() or '.xml'}",
            format="xml",
            sha256=member_hash,
            payload=member,
            lineage={
                "representation": "original_member",
                "original_source_id": entry["source_id"],
                "original_artifact_sha256": entry["artifact_sha256"],
                "zip_member": member_name,
                "member_sha256": member_hash,
                "transformation": "safe ZIP extraction only; member bytes unchanged",
            },
        )
        artifacts.append(original_artifact)

    derived_lookup = {
        id(element): (path, start, end) for element, _, path, start, end in derived_rows
    }
    candidates: list[dict[str, Any]] = []
    for element, text, literal_text, element_id in usable:
        raw = {
            "element_name": _local_name(element.tag),
            "attributes": {_local_name(k): v for k, v in sorted(element.attrib.items())},
            "text": text,
        }
        if element_id is not None and original_artifact is not None:
            artifact = original_artifact
            locator = f"id:{element_id}"
            lineage = {**artifact.lineage, "original_locator": locator}
        elif derived_artifact is not None:
            artifact = derived_artifact
            path, start, end = derived_lookup[id(element)]
            locator = f"chars:{start}:{end}"
            lineage = {
                **artifact.lineage,
                "transformation_locator": f"xml-path:{path}",
                "derived_locator": locator,
            }
        else:
            continue
        candidate = {
            "candidate_type": "xbrl_fact" if kind == "xbrl" else "document_element",
            "verification_state": "candidate",
            "source": _source(
                artifact,
                f"{entry['source_id']}:{member_hash[:12]}:{len(candidates)}",
                locator,
                literal_text
                if element_id is not None
                else f"{lineage['transformation_locator'][9:]}\t{text}",
            ),
            "lineage": lineage,
            "raw": raw,
            "normalization_suggestions": {},
        }
        candidate["candidate_id"] = _candidate_id(lineage, raw)
        candidates.append(candidate)
    return candidates, artifacts


def build_candidate_catalog(
    manifest: Mapping[str, Any],
    store: ArtifactStore,
    *,
    corp_code: str,
    fy: int,
    rcept_no: str,
    consolidation: str,
    max_candidates: int = 500,
    max_zip_files: int = 1_000,
    max_zip_bytes: int = 50 * 1024 * 1024,
) -> PreparedCandidates:
    """Validate originals and return a deterministic, bounded candidate snapshot."""
    if type(max_candidates) is not int or not 1 <= max_candidates <= MAX_CANDIDATES:
        raise CandidatePreparationError("candidate_limit_invalid")
    originals = _validated_originals(
        manifest,
        store,
        corp_code=corp_code,
        fy=fy,
        rcept_no=rcept_no,
        consolidation=consolidation,
    )
    groups: dict[str, list[dict[str, Any]]] = {
        "statements": [],
        "document": [],
        "xbrl": [],
    }
    artifacts: dict[str, CandidateArtifact] = {}
    truncated = False
    for kind, entry, payload in sorted(originals, key=lambda item: item[0]):
        if kind == "statements":
            found, artifact = _statement_candidates(
                entry, payload, corp_code=corp_code, fy=fy, rcept_no=rcept_no
            )
            artifacts[artifact.document_id] = artifact
        else:
            with tempfile.TemporaryDirectory(prefix="proofops-dart-") as temp:
                try:
                    members = store.extract_zip_safe(
                        payload,
                        temp,
                        max_files=max_zip_files,
                        max_total_size=max_zip_bytes,
                    )
                except (OSError, ValueError) as exc:
                    raise CandidatePreparationError("zip_rejected") from exc
                found = []
                for relative in sorted(members, key=lambda value: value.as_posix().casefold()):
                    remaining = max_candidates - len(found)
                    if remaining <= 0:
                        truncated = True
                        break
                    if relative.suffix.lower() not in {".xml", ".xbrl"}:
                        continue
                    member = (Path(temp) / relative).read_bytes()
                    extracted, member_artifacts = _xml_member_candidates(
                        entry,
                        relative.as_posix(),
                        member,
                        kind=kind,
                        candidate_limit=remaining,
                    )
                    found.extend(extracted)
                    for artifact in member_artifacts:
                        artifacts[artifact.document_id] = artifact
        remaining = max_candidates - len(groups[kind])
        groups[kind].extend(found[: max(0, remaining)])
        if len(found) > remaining:
            truncated = True
    candidates: list[dict[str, Any]] = []
    for index in range(max_candidates):
        added = False
        for kind in ("statements", "document", "xbrl"):
            if index < len(groups[kind]):
                candidates.append(groups[kind][index])
                added = True
                if len(candidates) == max_candidates:
                    break
        if len(candidates) == max_candidates or not added:
            break
    if sum(len(group) for group in groups.values()) > len(candidates):
        truncated = True
    referenced = {candidate["source"]["document_id"] for candidate in candidates}
    bounded_artifacts = tuple(artifacts[key] for key in sorted(artifacts) if key in referenced)
    catalog = {
        "schema_version": CATALOG_SCHEMA,
        "status": "candidate_only",
        "synthetic": manifest["synthetic"],
        "manifest_id": manifest["manifest_id"],
        "package_id": manifest["package_id"],
        "identity": {
            "corp_code": corp_code,
            "fy": fy,
            "rcept_no": rcept_no,
            "consolidation": consolidation,
        },
        "limits": {"max_candidates": max_candidates, "truncated": truncated},
        "trust": {
            "reviewed": False,
            "policy_approved": False,
            "search_complete": False,
            "notice": "Candidates and normalization suggestions require operator review.",
        },
        "artifacts": [
            {"document_id": item.document_id, **item.index_entry(), "lineage": item.lineage}
            for item in bounded_artifacts
        ],
        "candidates": candidates,
    }
    return PreparedCandidates(catalog=catalog, artifacts=bounded_artifacts)
