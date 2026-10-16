"""SEC-002 quarantine verification. No viewer, shell, model, or remote resource execution.

LocalUploadVault is a synthetic filesystem adapter, never an S3 implementation.
The upload API must supply server-owned object/version metadata and session tenant.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import monotonic
from typing import Any

HOSTED_NULL_NAVIGATION_PROFILE = "hosted-null-navigation-hx2-v1"
STRICT_PROFILES = frozenset({"strict-v1", HOSTED_NULL_NAVIGATION_PROFILE})


class UploadRejected(ValueError):
    """Code-only failure with optional structured inspection status; no source/parser text."""

    def __init__(self, code: str, *, security_metadata: dict | None = None):
        super().__init__(code)
        self.security_metadata = security_metadata or {}


@dataclass(frozen=True)
class PdfLimits:
    policy_profile: str = "strict-v1"
    max_expansion_ratio: int = 1000
    # Technical development limits, not corpus performance claims.
    max_bytes: int = 104_857_600
    max_pages: int = 300
    max_objects: int = 250_000
    max_decoded_bytes: int = 75_000_000
    timeout_seconds: float = 30
    memory_bytes: int = 512 * 1024 * 1024
    cpu_seconds: int = 20

    def __post_init__(self) -> None:
        if self.policy_profile not in {*STRICT_PROFILES, "display-v2"}:
            raise ValueError("Unsupported PDF security profile")
        for key, value in asdict(self).items():
            if key == "policy_profile":
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, float | int)
                or not math.isfinite(value)
                or value <= 0
                or (key != "timeout_seconds" and not isinstance(value, int))
            ):
                raise ValueError("Positive finite resource limits required")

    @classmethod
    def display(cls, **overrides) -> PdfLimits:
        """New-upload profile; legacy defaults remain byte-for-byte strict in behavior."""
        values: dict[str, Any] = dict(
            policy_profile="display-v2",
            max_objects=250_000,
            max_decoded_bytes=512 * 1024 * 1024,
            memory_bytes=1024 * 1024 * 1024,
            cpu_seconds=60,
            timeout_seconds=90,
        )
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True)
class QuarantinedPdf:
    tenant_id: str
    document_version_id: str
    object_version_id: str
    content: bytes = field(repr=False)
    expected_size: int
    expected_sha256: str


@dataclass(frozen=True)
class VerifiedPdf:
    source: QuarantinedPdf
    page_count: int
    display_content: bytes | None = field(default=None, repr=False)
    security_metadata: dict = field(default_factory=dict)
    analysis_content: bytes | None = field(default=None, repr=False)


def verify_quarantined_pdf(
    source: QuarantinedPdf,
    limits: PdfLimits,
    *,
    tenant_id: str,
) -> VerifiedPdf:
    """Verify an immutable quarantine snapshot; resource failures never become evidence absence.

    Storage callers must bound object reads by max_bytes before constructing the snapshot.
    On Windows a Job Object limits committed memory, CPU time and child processes.
    On Linux the child has hard address-space/CPU/process limits. macOS uses an RSS
    watchdog (sampled, not a kernel memory sandbox); deployment isolation is separate.
    """
    if tenant_id != source.tenant_id:
        raise UploadRejected("NOT_FOUND")
    from proofops.domain.values import _require_uuid

    try:
        _require_uuid("tenant_id", tenant_id)
        _require_uuid("document_version_id", source.document_version_id)
    except ValueError:
        raise UploadRejected("PDF_INVALID") from None
    if (
        not isinstance(source.object_version_id, str)
        or not 1 <= len(source.object_version_id) <= 1024
        or any(ord(character) < 32 for character in source.object_version_id)
    ):
        raise UploadRejected("PDF_INVALID")
    if not isinstance(source.content, bytes):
        raise UploadRejected("PDF_INVALID")
    if len(source.content) > limits.max_bytes:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    if (
        type(source.expected_size) is not int
        or source.expected_size != len(source.content)
        or sha256(source.content).hexdigest() != source.expected_sha256
    ):
        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", source.content):
        raise UploadRejected("PDF_INVALID")
    with TemporaryDirectory(prefix="proofops-quarantine-") as scratch:
        input_path = Path(scratch) / "source.pdf"
        input_path.write_bytes(source.content)
        input_path.chmod(0o400)
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            str(input_path),
            json.dumps(asdict(limits)),
        ]
        display_path = Path(scratch) / "display.pdf"
        command.append(str(display_path))
        deadline = monotonic() + limits.timeout_seconds
        with subprocess.Popen(
            command,
            shell=False,
            cwd=scratch,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            start_new_session=True,
        ) as process:
            try:
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                    try:
                        output, _ = process.communicate(timeout=min(0.02, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        if sys.platform == "darwin":
                            # ponytail: sampled macOS RSS; Linux hard limits for production.
                            rss = subprocess.run(
                                ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                                capture_output=True,
                                timeout=1,
                                check=False,
                            ).stdout.strip()
                            if rss and int(rss) * 1024 > limits.memory_bytes:
                                raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                if process.returncode:
                    raise UploadRejected(
                        "UPLOAD_LIMIT_EXCEEDED" if process.returncode < 0 else "PDF_INVALID"
                    )
                result = json.loads(output)
                if result["code"] != "verified":
                    raise UploadRejected(
                        result["code"], security_metadata=result.get("security", {})
                    )
                if result["security"]["source_sha256"] != source.expected_sha256:
                    raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
                display_content = None
                analysis_content = None
                if limits.policy_profile in STRICT_PROFILES and result.get("security", {}).get(
                    "encrypted"
                ):
                    with display_path.open("rb") as analysis_file:
                        analysis_content = analysis_file.read(limits.max_bytes + 1)
                    if len(analysis_content) > limits.max_bytes:
                        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                    if (
                        sha256(analysis_content).hexdigest()
                        != result["security"]["analysis_sha256"]
                    ):
                        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
                if limits.policy_profile == "display-v2":
                    with display_path.open("rb") as display_file:
                        display_content = display_file.read(limits.max_bytes + 1)
                    if len(display_content) > limits.max_bytes:
                        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                    if sha256(display_content).hexdigest() != result["security"]["display_sha256"]:
                        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
    # Resource telemetry varies per child; keep immutable retry/version metadata stable.
    result.get("security", {}).pop("peak_rss_bytes", None)
    return VerifiedPdf(
        source, result["pages"], display_content, result.get("security", {}), analysis_content
    )


def verify_pdf_file(
    path: Path,
    limits: PdfLimits,
    *,
    expected_size: int,
    expected_sha256: str,
    derived_path: Path | None = None,
    security_metadata: dict | None = None,
) -> int:
    """Strict verification of a service-owned disk snapshot; no whole-file body copy."""
    from hashlib import file_digest

    if limits.policy_profile not in STRICT_PROFILES:
        raise UploadRejected("PDF_INVALID")
    if path.is_symlink() or path.stat().st_size != expected_size:
        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    if expected_size > limits.max_bytes:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    with path.open("rb") as stream:
        if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", stream.read(16)):
            raise UploadRejected("PDF_INVALID")
        stream.seek(0)
        if file_digest(stream, "sha256").hexdigest() != expected_sha256:
            raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    deadline = monotonic() + limits.timeout_seconds
    with subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            str(path),
            json.dumps(asdict(limits)),
            *([str(derived_path)] if derived_path is not None else []),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        start_new_session=True,
    ) as process:
        try:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
                try:
                    output, _ = process.communicate(timeout=min(0.02, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if sys.platform == "darwin":
                        rss = subprocess.run(
                            ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                            capture_output=True,
                            timeout=1,
                            check=False,
                        ).stdout.strip()
                        if rss and int(rss) * 1024 > limits.memory_bytes:
                            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    if process.returncode:
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED" if process.returncode < 0 else "PDF_INVALID")
    result = json.loads(output)
    if result["code"] != "verified":
        raise UploadRejected(result["code"], security_metadata=result.get("security", {}))
    if result["security"]["source_sha256"] != expected_sha256:
        raise UploadRejected("UPLOAD_INTEGRITY_MISMATCH")
    if security_metadata is not None:
        security_metadata.update(result.get("security", {}))
    return result["pages"]


class LocalUploadVault:
    """Synthetic local adapter: private root, atomic create-only promotion, no AWS calls.

    Use only with a service-owned root; uploaders must never have filesystem access.
    Upload state/CAS and the production versioned S3 adapter remain separate.
    """

    def __init__(self, root: Path):
        self.root = root

    def original_path(self, verified: VerifiedPdf) -> Path:
        source = verified.source
        return self.root / "original" / source.tenant_id / f"{source.document_version_id}.pdf"

    def verify_and_promote(
        self,
        source: QuarantinedPdf,
        limits: PdfLimits,
        *,
        tenant_id: str,
    ) -> VerifiedPdf:
        verified = verify_quarantined_pdf(source, limits, tenant_id=tenant_id)
        target = self.original_path(verified)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with NamedTemporaryFile(dir=target.parent) as staged:
            staged.write(source.content)
            staged.flush()
            os.fsync(staged.fileno())
            os.chmod(staged.name, 0o400)
            try:
                os.link(staged.name, target)  # Atomic create-only; never replace a prior revision.
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != source.content:
                    raise UploadRejected("VERSION_CONFLICT") from None
        for suffix, content in (
            (".display-v2.pdf", verified.display_content),
            (".decrypted.pdf", verified.analysis_content),
        ):
            if content is None:
                continue
            display_target = target.with_suffix(suffix)
            with NamedTemporaryFile(dir=target.parent) as staged:
                staged.write(content)
                staged.flush()
                os.fsync(staged.fileno())
                os.chmod(staged.name, 0o400)
                try:
                    os.link(staged.name, display_target)
                except FileExistsError:
                    if display_target.is_symlink() or display_target.read_bytes() != content:
                        raise UploadRejected("VERSION_CONFLICT") from None
        return verified


def _windows_limits(limits: PdfLimits) -> int:
    """Attach this parser child to a fail-closed Windows Job Object.

    The returned OS handle is intentionally held until process exit. This helper
    must never be called in the API process. Layouts/flags follow Microsoft's
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION and JOBOBJECT_BASIC_LIMIT_INFORMATION.
    """
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io_counters", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise UploadRejected("PDF_INVALID")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise UploadRejected("PDF_INVALID")
    baseline = Extended()
    if not kernel.QueryInformationJobObject(
        job,
        9,
        ctypes.byref(baseline),
        ctypes.sizeof(baseline),
        None,
    ):
        kernel.CloseHandle(job)
        raise UploadRejected("PDF_INVALID")
    if baseline.peak_process_memory > limits.memory_bytes:
        kernel.CloseHandle(job)
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    info = Extended()
    info.basic.process_time = limits.cpu_seconds * 10_000_000
    info.basic.active_processes = 1
    info.basic.flags = 0x00000002 | 0x00000008 | 0x00000100
    info.process_memory = limits.memory_bytes
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel.CloseHandle(job)
        raise UploadRejected("PDF_INVALID")
    return job


def _inspect_legacy(
    path: str,
    limits: PdfLimits,
    *,
    recover_xref: bool = False,
    derived_output: Path | None = None,
    security: dict | None = None,
) -> int:
    # Only the resource-limited child imports/parses untrusted PDF structures.
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_bytes, limits.max_bytes))
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

    if sys.platform == "win32":
        _windows_limits(limits)
    elif sys.platform == "linux":
        # Load trusted parser code before constraining its address space. An undersized
        # budget must be a resource rejection, not a shared-library import/PDF error.
        current_vm = int(Path("/proc/self/statm").read_text().split()[0]) * resource.getpagesize()
        if current_vm > limits.memory_bytes:
            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))

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

            def decrypt_object(obj, idnum, generation, *, strict=True):
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


def _inspect_strict(path: str, limits: PdfLimits, output: Path | None = None) -> dict:
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
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_bytes, limits.max_bytes))
    from pypdf import apply_configuration
    from pypdf.errors import LimitReachedError, PdfReadError, PdfStreamError

    if sys.platform == "win32":
        _windows_limits(limits)
    elif sys.platform == "linux":
        current_vm = int(Path("/proc/self/statm").read_text().split()[0]) * resource.getpagesize()
        if current_vm > limits.memory_bytes:
            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
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


def _inspect(path: str, limits: PdfLimits) -> int:
    if limits.policy_profile == "strict-v1":
        return _inspect_strict(path, limits)["pages"]
    with TemporaryDirectory(prefix="proofops-display-") as temporary:
        return _inspect_display(path, limits, Path(temporary) / "display.pdf")["pages"]


if __name__ == "__main__":
    import logging

    logging.disable(logging.CRITICAL)
    try:
        limits = PdfLimits(**json.loads(sys.argv[2]))
        if limits.policy_profile == "display-v2":
            with TemporaryDirectory(prefix="proofops-display-cli-") as scratch:
                output = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(scratch) / "display.pdf"
                security = _inspect_display(sys.argv[1], limits, output)
                print(
                    json.dumps(
                        {"code": "verified", "pages": security["pages"], "security": security}
                    )
                )
        else:
            with TemporaryDirectory(prefix="proofops-strict-cli-") as scratch:
                output = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(scratch) / "decrypted.pdf"
                print(json.dumps(_inspect_strict(sys.argv[1], limits, output)))
    except MemoryError:
        print('{"code":"UPLOAD_LIMIT_EXCEEDED"}')
    except Exception as error:
        from pypdf.errors import LimitReachedError

        code = (
            "UPLOAD_LIMIT_EXCEEDED"
            if isinstance(error, MemoryError | LimitReachedError)
            else str(error)
            if isinstance(error, UploadRejected)
            else "PDF_INVALID"
        )
        failure: dict[str, Any] = {"code": code}
        if isinstance(error, UploadRejected) and error.security_metadata:
            failure["security"] = error.security_metadata
        if sys.platform != "win32":
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            failure.setdefault("security", {})["peak_rss_bytes"] = (
                peak if sys.platform == "darwin" else peak * 1024
            )
        print(json.dumps(failure))
