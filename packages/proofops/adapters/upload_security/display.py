"""Display-only sanitation; never replace inspection of the original PDF."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.application.upload_contracts import (
    PdfLimits,
    UploadRejected,
)

from .limits import apply_basic_limits, apply_parser_limits

_DISPLAY_REMOVE = {
    "/AA",
    "/OpenAction",
    "/JavaScript",
    "/JS",
    "/Launch",
    "/SubmitForm",
    "/ImportData",
    "/GoToR",
    "/GoToE",
    "/Rendition",
    "/RichMedia",
    "/RichMediaContent",
    "/RichMediaSettings",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/XFA",
    "/AcroForm",
    "/Annots",
    "/Names",
    "/AF",
    "/EF",
    "/Collection",
    "/Metadata",
    "/PresSteps",
    "/Next",
    "/URI",
    "/Sound",
    "/Movie",
    "/3D",
    "/3DD",
}
_ACTION_SUBTYPES = {
    "/GoTo",
    "/GoToR",
    "/GoToE",
    "/Launch",
    "/Thread",
    "/URI",
    "/Sound",
    "/Movie",
    "/Hide",
    "/Named",
    "/SubmitForm",
    "/ResetForm",
    "/ImportData",
    "/JavaScript",
    "/SetOCGState",
    "/Rendition",
    "/Trans",
    "/GoTo3DView",
}


def _display_reader(path: str, limits: PdfLimits, output: Path, *, strict: bool) -> dict:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        IndirectObject,
        NameObject,
        PdfObject,
        StreamObject,
    )

    reader = PdfReader(path, strict=strict, root_object_recovery_limit=limits.max_objects)
    encrypted = reader.is_encrypted
    if encrypted and not reader.decrypt(""):
        raise UploadRejected("PDF_PASSWORD_REQUIRED")
    permissions = int(reader.user_access_permissions or 0) if encrypted else None
    pages = len(reader.pages)
    if pages < 1:
        raise UploadRejected("PDF_INVALID")
    if pages > limits.max_pages:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    references = [
        (number, generation)
        for generation, entries in reader.xref.items()
        for number in entries
        if number != 0 and generation != 65535
    ] + [(number, 0) for number in reader.xref_objStm]
    if len(references) > limits.max_objects:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    pending: list[PdfObject | None] = [
        IndirectObject(number, generation, reader) for number, generation in references
    ]
    pending.append(reader.trailer)
    # Reader.pages wraps page dictionaries in separate PageObjects; scan BOTH
    # representations so deletions also apply to the actual pages copied below.
    pending.extend(reader.pages)
    seen: set[int] = set()
    dictionaries: list[DictionaryObject] = []
    decoded = 0
    max_ratio = 0.0
    missing = 0
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            value = value.get_object()
            if value is None:
                missing += 1
        if not isinstance(value, DictionaryObject | ArrayObject) or id(value) in seen:
            continue
        seen.add(id(value))
        if len(seen) > limits.max_objects:
            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        if isinstance(value, DictionaryObject):
            if isinstance(value, StreamObject):
                # External stream files cannot be resolved by any analysis engine.
                if "/F" in value:
                    raise UploadRejected("PDF_INVALID")
                filters = value.get("/Filter", [])
                if not isinstance(filters, list):
                    filters = [filters]
                if filters == ["/Crypt"] and str(value.get("/Type", "")) == "/Metadata":
                    # EncryptMetadata=false reports carry an identity Crypt wrapper.
                    # Metadata is omitted from the display; count its raw bytes, never
                    # invoke a crypt/command decoder or deliver the wrapper.
                    length = len(value._data)
                    decoded += length
                    if decoded > limits.max_decoded_bytes:
                        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                    pending.extend(value.values())
                    dictionaries.append(value)
                    continue
                if any(
                    str(item)
                    not in {
                        "/FlateDecode",
                        "/ASCIIHexDecode",
                        "/ASCII85Decode",
                        "/LZWDecode",
                        "/RunLengthDecode",
                        "/DCTDecode",
                        "/JPXDecode",
                        "/CCITTFaxDecode",
                    }
                    for item in filters
                ):
                    raise UploadRejected("PDF_INVALID")
                length = len(value.get_data())
                decoded += length
                ratio = length / max(1, len(value._data))
                max_ratio = max(max_ratio, ratio)
                if decoded > limits.max_decoded_bytes or (
                    length > 1_000_000 and ratio > limits.max_expansion_ratio
                ):
                    raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                # Keep encoded source streams; don't retain decoded image/text copies.
                if hasattr(value, "decoded_self"):
                    value.decoded_self = None
            pending.extend(value.values())
            dictionaries.append(value)
        else:
            pending.extend(value)
    if decoded > max(1, Path(path).stat().st_size) * limits.max_expansion_ratio:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    removed = 0
    for value in dictionaries:
        if (
            str(value.get("/Type", "")) in {"/Action", "/EmbeddedFile", "/Metadata"}
            or str(value.get("/S", "")) in _ACTION_SUBTYPES
        ):
            value.clear()
            if isinstance(value, StreamObject):
                value._data = b""
            removed += 1
            continue
        for key in _DISPLAY_REMOVE.intersection(value.keys()):
            del value[key]
            removed += 1
        # /A on tagged structure elements is an attribute, not an action.
        action = value.get("/A")
        if isinstance(action, IndirectObject):
            action = action.get_object()
        if isinstance(action, DictionaryObject) and ("/S" in action or not action):
            del value["/A"]
            removed += 1
    # Fresh page-only catalog: no outlines, forms, attachments, names or orphan xref objects.
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    # Clone the sanitized configuration through the same writer translation map as
    # page resources, so OCG references keep their default ON/OFF and View/Print usage.
    optional_content = reader.root_object.get("/OCProperties")
    if isinstance(optional_content, IndirectObject):
        optional_content = optional_content.get_object()
    if optional_content is not None:
        if not isinstance(optional_content, DictionaryObject):
            raise UploadRejected("PDF_INVALID")
        writer.root_object[NameObject("/OCProperties")] = optional_content.clone(writer)
    writer.write(output)
    if output.stat().st_size > limits.max_bytes:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    return dict(
        pages=pages,
        scanned_objects=len(seen),
        indexed_objects=len(references),
        encrypted=encrypted,
        permissions=permissions,
        decoded_bytes=decoded,
        max_stream_expansion_ratio=max_ratio,
        removed_entries=removed,
        missing_references=missing,
        parser="pypdf-strict" if strict else "pypdf-tolerant",
    )


def _inspect_display(path: str, limits: PdfLimits, output: Path) -> dict:
    # All retries share ONE process, CPU/memory/deadline budget. No action execution,
    # viewer form environment, shell, network callbacks, or external stream resolution.
    apply_basic_limits(limits)
    from pypdf import apply_configuration
    from pypdf.errors import LimitReachedError, PdfReadError, PdfStreamError

    apply_parser_limits(limits)
    if Path(path).stat().st_size > limits.max_bytes:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    with apply_configuration(
        maximum_declared_stream_length=limits.max_bytes,
        array_based_stream_maximum_output_length=limits.max_decoded_bytes,
        zlib_maximum_output_length=limits.max_decoded_bytes,
        lzw_maximum_output_length=limits.max_decoded_bytes,
        run_length_maximum_output_length=limits.max_decoded_bytes,
        jbig2dec_binary=None,
        page_tree_maximum_entries=limits.max_objects,
    ):
        failures = []
        for strict in (True, False):
            try:
                result = _display_reader(path, limits, output, strict=strict)
                break
            except LimitReachedError:
                raise UploadRejected("UPLOAD_LIMIT_EXCEEDED") from None
            except (PdfReadError, PdfStreamError) as error:
                failures.append(type(error).__name__)
        else:
            # PDFium save may discard unreadable/orphan objects. A scan of its
            # replacement object set cannot establish safety of the analysis original.
            raise UploadRejected(
                "PDF_INVALID",
                security_metadata=dict(
                    original_inspection="incomplete",
                    repaired_inspection="not_attempted",
                    parser_retry_errors=failures,
                ),
            )
        result.update(
            original_inspection="complete",
            repaired_inspection="not_attempted",
            display_inspection="sanitized",
            policy_profile=limits.policy_profile,
            limits=asdict(limits),
            interactive_content="removed-including-annotations-and-forms",
            derived=True,
            source_sha256=sha256(Path(path).read_bytes()).hexdigest(),
            display_sha256=sha256(output.read_bytes()).hexdigest(),
            parser_retry_errors=failures,
        )
        return result
