"""Complete original PDF inspection and strict-profile derived-copy verification."""

from __future__ import annotations

import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from proofops.application.upload_contracts import (
    HOSTED_NULL_NAVIGATION_PROFILE,
    PdfLimits,
    UploadRejected,
)

from .limits import apply_basic_limits, apply_parser_limits


def _inspect_legacy(
    path: str,
    limits: PdfLimits,
    *,
    recover_xref: bool = False,
    derived_output: Path | None = None,
    security: dict[str, Any] | None = None,
) -> int:
    # Only the resource-limited child imports/parses untrusted PDF structures.
    apply_basic_limits(limits)
    from pypdf import PdfReader, apply_configuration
    from pypdf.generic import (
        ArrayObject,
        BooleanObject,
        DictionaryObject,
        IndirectObject,
        NameObject,
        PdfObject,
        StreamObject,
    )

    apply_parser_limits(limits)

    with (
        Path(path).open("rb") as source_file,
        apply_configuration(
            maximum_declared_stream_length=limits.max_bytes,
            array_based_stream_maximum_output_length=limits.max_decoded_bytes,
            zlib_maximum_output_length=limits.max_decoded_bytes,
            lzw_maximum_output_length=limits.max_decoded_bytes,
            run_length_maximum_output_length=limits.max_decoded_bytes,
            jbig2dec_binary=None,
            page_tree_maximum_entries=limits.max_objects,
        ),
    ):
        reader = PdfReader(
            source_file, strict=not recover_xref, root_object_recovery_limit=limits.max_objects
        )
        # Recovery is limited to constructing the xref map. Every indexed object,
        # stream, action and destination is subsequently read with strict checks.
        reader.strict = True
        encrypted = reader.is_encrypted
        if encrypted and not reader.decrypt(""):
            raise UploadRejected("PDF_PASSWORD_REQUIRED")
        encryption_dictionary = reader.trailer.get("/Encrypt")
        if isinstance(encryption_dictionary, IndirectObject):
            encryption_dictionary = encryption_dictionary.get_object()
        encrypt_metadata = (
            encryption_dictionary.get("/EncryptMetadata")
            if isinstance(encryption_dictionary, DictionaryObject)
            else None
        )
        plaintext_metadata = (
            isinstance(encrypt_metadata, BooleanObject) and not encrypt_metadata.value
        )
        if plaintext_metadata:
            # ISO encryption flag excludes Metadata streams from encryption. pypdf
            # 6.19 otherwise attempts AES decryption of their plaintext XML bytes.
            encryption = reader._encryption
            assert encryption is not None
            decrypt = encryption.decrypt_object

            def decrypt_object(
                obj: PdfObject, idnum: int, generation: int, *, strict: bool = True
            ) -> PdfObject:
                if isinstance(obj, StreamObject) and obj.get("/Type") == "/Metadata":
                    return obj
                return decrypt(obj, idnum, generation, strict=strict)

            setattr(encryption, "decrypt_object", decrypt_object)
        pages = len(reader.pages)
        if pages == 0:
            raise UploadRejected("PDF_INVALID")
        if pages > limits.max_pages:
            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        # Inspect every indexed object, including compressed and otherwise unreachable actions.
        references = [
            (number, generation)
            for generation, entries in reader.xref.items()
            for number in entries
            if number != 0 and generation != 65535
        ]
        references.extend((number, 0) for number in reader.xref_objStm)
        if security is not None:
            original_index = security.get("_original_index", {})
            if recover_xref and original_index:
                lost = set(original_index) - set(references)
                if any(original_index[ref] != 0 for ref in lost):
                    raise UploadRejected("PDF_INVALID")
                if lost:
                    # Some exporters mark undefined objects as live with offset 0.
                    # Referenced undefined objects still fail under reader.strict.
                    # Physical definitions hidden behind those bad entries must
                    # remain in the complete security scan, including orphans.
                    source_file.seek(0)
                    raw = source_file.read(limits.max_bytes + 1)
                    for number, generation in lost:
                        if re.search(
                            rb"(?:^|\s)"
                            + str(number).encode()
                            + rb"\s+"
                            + str(generation).encode()
                            + rb"\s+obj\b",
                            raw,
                        ):
                            references.append((number, generation))
                    del raw
                security["unused_zero_offset_entries"] = len(lost)
            elif not recover_xref:
                security["_original_index"] = {
                    ref: reader.xref.get(ref[1], {}).get(ref[0], -1) for ref in references
                }
        if len(references) > limits.max_objects:
            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        pending: list[PdfObject | None] = [
            IndirectObject(number, generation, reader) for number, generation in references
        ]
        seen: set[int] = set()
        decoded = 0
        # Action dictionaries reachable from /AA, /OpenAction, or an annotation's
        # direct /A are validated by explicit subtype allowlist below; they must
        # never be treated as merely "present -> reject" (that rejected inert
        # /D -> /Named navigation) nor skipped as "present -> ignore" (that would
        # defeat fail-closed intent).
        action_table_keys = {"/AA"}
        direct_action_keys = {"/OpenAction", "/A"}
        # /A also names structure-element attribute objects/arrays in tagged
        # PDFs; only treat it as an action when its value is action-shaped
        # (a dict carrying /S), never a bare attribute dict/array.
        # These constructs are inherently dangerous wherever they occur, including
        # inside an action dictionary's own keys (e.g. a /Launch action's /F).
        forbidden = {
            "/JavaScript",
            "/JS",
            "/Launch",
            "/SubmitForm",
            "/ImportData",
            "/GoToR",
            "/GoToE",
            "/Rendition",
            "/RichMedia",
            "/EmbeddedFiles",
            "/EmbeddedFile",
            "/XFA",
        }
        # Inert by allowlist: pure in-viewer navigation with no code execution,
        # filesystem, or network access. /Named and /GoTo are in-viewer
        # navigation and remain inert even for automatic triggers. /URI (data
        # only, never fetched here) and /Hide are only allowed for explicit
        # user-gesture triggers -- annotation/outline /A and Widget mouse
        # down/up /AA D//U. Widget hover/focus may also /Hide, but never /URI.
        # Automatic /OpenAction and other /AA events stay rejected. /Hide toggles this
        # document's own annotations/form fields (ISO 32000-1 Table 210 /
        # PDF 1.7 Table 8.60): its /T names an annotation dictionary, a text
        # field name string, or an array of those, and its optional /H is a
        # boolean; it never resolves a file, URL, or embedded target. The
        # Widget interaction exceptions are applied at their /AA call site.
        inert_action_subtypes = {"/Named", "/GoTo"}
        user_gesture_inert_subtypes = inert_action_subtypes | {"/URI", "/Hide"}
        link_click_subtypes = user_gesture_inert_subtypes | {"/GoToR"}
        widget_interaction_subtypes = inert_action_subtypes | {"/Hide"}
        inert_named_destinations = {
            "/NextPage",
            "/PrevPage",
            "/FirstPage",
            "/LastPage",
            "/GoBack",
            "/GoForward",
        }

        def is_internal_destination(destination: object) -> bool:
            """A /GoTo /D must be a name/string (Dests-tree lookup) or an
            explicit [page, fit-mode, ...] array pointing at a page in this
            document. Never accept destinations shaped like remote/embedded
            file targets (those use /GoToR //GoToE with their own /F, which
            never reach this function under subtype /GoTo)."""
            if isinstance(destination, IndirectObject):
                destination = destination.get_object()
            if isinstance(destination, str):
                return True
            if isinstance(destination, ArrayObject):
                if len(destination) < 2:
                    return False
                page_ref = destination[0]
                if (
                    limits.policy_profile == HOSTED_NULL_NAVIGATION_PROFILE
                    and isinstance(page_ref, IndirectObject)
                    and page_ref.idnum == 0
                    and page_ref.generation == 0
                ):
                    # An internal GoTo with a null page is an inert no-op, not an
                    # external file or an executable action. Do not resolve it.
                    return True
                page_target = (
                    page_ref.get_object() if isinstance(page_ref, IndirectObject) else page_ref
                )
                return isinstance(page_target, DictionaryObject) and str(
                    page_target.get("/Type", "")
                ) in {"/Page", "/Pages"}
            return False

        def is_internal_hide_target(target: object) -> bool:
            """A /Hide /T names this document's own field(s)/annotation(s)
            (PDF 1.7 Table 8.60): a text field-name string, an annotation
            dictionary reference, or an array mixing those. An annotation
            dictionary is validated by its own /Type /Annot (its /F is the
            integer annotation-flags entry, NOT an external file specification,
            so /F is legal here); a file-specification-shaped dict or any
            forbidden construct is rejected. Nothing here is ever resolved,
            fetched, or executed."""
            if isinstance(target, IndirectObject):
                target = target.get_object()
            if isinstance(target, str):
                return True
            if isinstance(target, DictionaryObject):
                if forbidden.intersection(target.keys()):
                    return False
                # Only a genuine annotation dictionary is an acceptable object
                # target; /FS or /EF mark a file specification, never a hide
                # target, and an /F without /Type /Annot is treated as a
                # file-spec shape rather than annotation flags.
                if {"/FS", "/EF"}.intersection(target.keys()):
                    return False
                if str(target.get("/Type", "")) != "/Annot":
                    return False
                return True
            if isinstance(target, ArrayObject):
                return len(target) > 0 and all(is_internal_hide_target(entry) for entry in target)
            return False

        def reject_dangerous_action_chain(
            action: object,
            *,
            depth: int = 0,
            chain_seen: set[int] | None = None,
            allowed_subtypes: frozenset[str] = frozenset(inert_action_subtypes),
            allow_user_named_action: bool = False,
        ) -> None:
            """Validate one action dict/array fail-closed; recurse only into its
            own /Next chain (never treat a raw /OpenAction destination array as
            an action array -- see the caller, which only reaches here with true
            action dicts/action-arrays already distinguished from destination
            arrays).

            Anything not in `allowed_subtypes` is rejected, including
            missing/unknown /S, dangerous /S, or malformed /Next links. Hidden
            or unreachable placement (e.g. inside /AA rather than the page tree)
            does not exempt an action from this check. `chain_seen` bounds
            recursive work on shared/cyclic /Next graphs by unique node
            identity, independent of the `depth` cap for pathologically long
            linear chains.
            """
            if chain_seen is None:
                chain_seen = set()
            if depth > 32:  # bounded traversal of pathological /Next chains
                raise UploadRejected("PDF_INVALID")
            if isinstance(action, IndirectObject):
                action = action.get_object()
            if isinstance(action, ArrayObject):
                for item in action:
                    reject_dangerous_action_chain(
                        item,
                        depth=depth + 1,
                        chain_seen=chain_seen,
                        allowed_subtypes=allowed_subtypes,
                        allow_user_named_action=allow_user_named_action,
                    )
                return
            if not isinstance(action, DictionaryObject):
                raise UploadRejected("PDF_INVALID")
            if id(action) in chain_seen:
                return  # already validated via another /Next reference; do not re-walk
            chain_seen.add(id(action))
            subtype = action.get("/S")
            subtype_name = str(subtype) if subtype is not None else ""
            if subtype_name not in allowed_subtypes:
                raise UploadRejected("PDF_INVALID")
            if forbidden.intersection(action.keys()):
                raise UploadRejected("PDF_INVALID")
            if subtype_name == "/Named":
                destination = action.get("/N")
                # Print/Find open viewer UI only on a user gesture, never automatically.
                if str(destination) not in inert_named_destinations and not (
                    allow_user_named_action
                    and str(destination)
                    in {"/Print", "/Find", "/FitPage", "/FitWidth", "/FitHeight", "/ActualSize"}
                ):
                    raise UploadRejected("PDF_INVALID")
            elif subtype_name == "/GoTo":
                # /GoTo must name a page or destination in this document.
                if "/D" not in action or not is_internal_destination(action.get("/D")):
                    raise UploadRejected("PDF_INVALID")
            elif subtype_name == "/GoToR":
                # Remote navigation is stored as data only. It is permitted only
                # at a Link /A call site, never an automatic or Widget trigger.
                target = action.get("/F")
                if isinstance(target, IndirectObject):
                    target = target.get_object()
                if not isinstance(target, str | DictionaryObject):
                    raise UploadRejected("PDF_INVALID")
                if isinstance(target, DictionaryObject) and (
                    str(target.get("/Type", "")) != "/Filespec"
                    or not isinstance(target.get("/F"), str)
                    or {"/EF", "/AF", "/FS"}.intersection(target)
                ):
                    raise UploadRejected("PDF_INVALID")
                destination = action.get("/D")
                if isinstance(destination, IndirectObject):
                    destination = destination.get_object()
                if not isinstance(destination, str | ArrayObject):
                    raise UploadRejected("PDF_INVALID")
                if isinstance(destination, ArrayObject) and (
                    len(destination) < 2
                    or not isinstance(destination[0], int)
                    or isinstance(destination[0], bool)
                    or destination[0] < 0
                ):
                    raise UploadRejected("PDF_INVALID")
            elif subtype_name == "/URI" and "/URI" not in action:
                raise UploadRejected("PDF_INVALID")
            elif subtype_name == "/Hide":
                # /Hide only toggles visibility of this document's own fields
                # /annotations and is permitted solely under a user gesture (it
                # is absent from inert_action_subtypes, so an automatic
                # /OpenAction or automatic /AA event carrying /Hide is rejected
                # before reaching here). Its /T must name an annotation dict, a
                # text field-name string, or an array of those; a /Hide with no
                # /T is a malformed no-op and a /T shaped like a file
                # specification is not a legitimate hide target. Its optional
                # /H, when present, is a boolean. No target is ever resolved,
                # fetched, or executed by this checker.
                hidden_flag = action.get("/H")
                if hidden_flag is not None and not isinstance(hidden_flag, BooleanObject):
                    raise UploadRejected("PDF_INVALID")
                if "/T" not in action or not is_internal_hide_target(action.get("/T")):
                    raise UploadRejected("PDF_INVALID")
            if "/Next" in action:
                reject_dangerous_action_chain(
                    action.get("/Next"),
                    depth=depth + 1,
                    chain_seen=chain_seen,
                    allowed_subtypes=allowed_subtypes,
                    allow_user_named_action=allow_user_named_action,
                )

        def reject_dangerous_open_action(
            open_action: object, *, allow_uri: bool = False, link_click: bool = False
        ) -> None:
            """/OpenAction (like a /GoTo /D) may be either an action dictionary
            or a bare destination array `[page fit-mode ...]` (PDF 32000-1
            12.3.2). A bare destination array must never be walked as if its
            elements were actions -- that misreads a legitimate direct
            destination as a malformed action list and rejects harmless files.
            /URI is only inert when reached via an annotation/outline's direct
            /A (`allow_uri=True`): that fires solely on an explicit user
            gesture, unlike /OpenAction which auto-fires on document open.
            """
            if isinstance(open_action, IndirectObject):
                open_action = open_action.get_object()
            if isinstance(open_action, ArrayObject):
                if not is_internal_destination(open_action):
                    raise UploadRejected("PDF_INVALID")
                return
            reject_dangerous_action_chain(
                open_action,
                allowed_subtypes=frozenset(link_click_subtypes)
                if link_click
                else frozenset(user_gesture_inert_subtypes)
                if allow_uri
                else frozenset(inert_action_subtypes),
                allow_user_named_action=allow_uri,
            )

        null_references = 0
        while pending:
            value = pending.pop()
            if isinstance(value, IndirectObject):
                # Object 0 is the reserved null object. Orion's optional structure
                # entries use 0 0 R; there is no payload to resolve or execute.
                # Every nonzero reference and all action targets stay strict.
                if (
                    limits.policy_profile == HOSTED_NULL_NAVIGATION_PROFILE
                    and value.idnum == 0
                    and value.generation == 0
                ):
                    null_references += 1
                    continue
                value = value.get_object()
            if isinstance(value, DictionaryObject | ArrayObject):
                if id(value) in seen:
                    # Already inspected via another reference (shared/fan-in
                    # nodes); do not recount or re-enqueue its children.
                    continue
                seen.add(id(value))
            if len(seen) > limits.max_objects:
                raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
            if isinstance(value, DictionaryObject):
                if forbidden.intersection(value.keys()) or (
                    str(value.get("/S", "")) in forbidden and str(value.get("/S", "")) != "/GoToR"
                ):
                    raise UploadRejected("PDF_INVALID")
                if str(value.get("/Type", "")) == "/EmbeddedFile":
                    raise UploadRejected("PDF_INVALID")
                # A free-floating action dict (/Type /Action) reachable only via
                # xref/objStm indexing -- not necessarily via /AA, /OpenAction, or
                # /A -- must still be classified fail-closed even if nothing
                # currently points to it (hidden/unreachable active actions).
                # The xref scan has no trigger context. URI/Print may be stored
                # here, but every actual reference is rechecked below: automatic
                # triggers remain strict regardless of shared-object scan order.
                if str(value.get("/Type", "")) == "/Action" or value.get("/S") == "/GoToR":
                    reject_dangerous_action_chain(
                        value,
                        allowed_subtypes=frozenset(link_click_subtypes),
                        allow_user_named_action=True,
                    )
                for action_key in action_table_keys.intersection(value.keys()):
                    action_table = value.get(action_key)
                    if isinstance(action_table, IndirectObject):
                        action_table = action_table.get_object()
                    if isinstance(action_table, DictionaryObject):
                        for trigger, trigger_action in action_table.items():
                            # Widget clicks may follow links/open viewer UI. Hover
                            # and focus may only toggle internal annotation visibility
                            # or navigate internally, including every /Next link.
                            widget = (
                                str(value.get("/Type", "")) == "/Annot"
                                and str(value.get("/Subtype", "")) == "/Widget"
                            )
                            gesture = widget and str(trigger) in {"/D", "/U"}
                            interaction = widget and str(trigger) in {"/E", "/X", "/Fo", "/Bl"}
                            allowed = (
                                user_gesture_inert_subtypes
                                if gesture
                                else widget_interaction_subtypes
                                if interaction
                                else inert_action_subtypes
                            )
                            reject_dangerous_action_chain(
                                trigger_action,
                                allowed_subtypes=frozenset(allowed),
                                allow_user_named_action=gesture,
                            )
                    else:
                        raise UploadRejected("PDF_INVALID")
                for action_key in direct_action_keys.intersection(value.keys()):
                    target = value.get(action_key)
                    resolved = target.get_object() if isinstance(target, IndirectObject) else target
                    if action_key == "/A" and not (
                        isinstance(resolved, DictionaryObject) and "/S" in resolved
                    ):
                        continue  # structure-element attributes, not an action
                    reject_dangerous_open_action(
                        target,
                        allow_uri=action_key == "/A",
                        link_click=(
                            action_key == "/A"
                            and value.get("/Type") == "/Annot"
                            and value.get("/Subtype") == "/Link"
                        ),
                    )
                if isinstance(value, StreamObject):
                    if "/F" in value:  # External stream file; never resolve/fetch it.
                        raise UploadRejected("PDF_INVALID")
                    filters = value.get("/Filter", [])
                    if (
                        plaintext_metadata
                        and value.get("/Type") == "/Metadata"
                        and filters == ["/Crypt"]
                        and "/DecodeParms" not in value
                    ):
                        # Default Crypt here is Identity. Normalize the inspected
                        # plaintext stream in memory so its decrypted clone has no
                        # encryption filter. Original disk bytes stay immutable.
                        value[NameObject("/Filter")] = ArrayObject()
                        filters = []
                    if not isinstance(filters, list):
                        filters = [filters]
                    allowed = {
                        "/FlateDecode",
                        "/ASCIIHexDecode",
                        "/ASCII85Decode",
                        "/LZWDecode",
                        "/RunLengthDecode",
                        "/DCTDecode",
                        "/JPXDecode",
                        "/CCITTFaxDecode",
                    }
                    if any(str(item) not in allowed for item in filters):
                        raise UploadRejected("PDF_INVALID")
                    decoded += len(value.get_data())
                    # Inspection still visits every object, but decoded XObjects/images
                    # are not retained until the entire document has been walked.
                    if hasattr(value, "decoded_self"):
                        value.decoded_self = None
                    if decoded > limits.max_decoded_bytes:
                        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                pending.extend(value.values())
            elif isinstance(value, ArrayObject):
                pending.extend(value)
        if security is not None:
            security.update(
                encrypted=encrypted,
                parser_xref_recovered=recover_xref,
                null_object_references=null_references,
                objects=len(references),
                nodes=len(seen),
                decoded_bytes=decoded,
            )
        if encrypted and derived_output is not None:
            from pypdf import PdfWriter

            writer = PdfWriter(clone_from=reader)
            with derived_output.open("xb") as derived:
                writer.write(derived)
            if derived_output.stat().st_size > limits.max_bytes:
                raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        return pages


def _inspect_strict(path: str, limits: PdfLimits, output: Path | None = None) -> dict[str, Any]:
    from hashlib import file_digest

    from pypdf.errors import PdfReadError

    security: dict[str, Any] = {}
    try:
        pages = _inspect_legacy(path, limits, derived_output=output, security=security)
    except PdfReadError:
        pages = _inspect_legacy(
            path, limits, recover_xref=True, derived_output=output, security=security
        )
    security.pop("_original_index", None)
    with Path(path).open("rb") as source:
        original_sha = file_digest(source, "sha256").hexdigest()
    security.update(
        policy_profile=limits.policy_profile,
        source_sha256=original_sha,
        original_inspection="complete",
        limits=asdict(limits),
    )
    if output is not None and security["encrypted"]:
        # Reinspect the entire written clone before any caller promotes it.
        if _inspect_legacy(str(output), limits) != pages:
            raise UploadRejected("PDF_INVALID")
        with output.open("rb") as derived:
            security["analysis_sha256"] = file_digest(derived, "sha256").hexdigest()
    if sys.platform != "win32":
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        security["peak_rss_bytes"] = peak if sys.platform == "darwin" else peak * 1024
    return {"code": "verified", "pages": pages, "security": security}
