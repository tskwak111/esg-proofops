"""FX6b: original-report structures, isolated inspection and dangerous mixtures."""

import json
import re
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unicodedata import normalize

import pytest
from proofops.application.uploads_security import PdfLimits, UploadRejected, verify_pdf_file
from proofops_api.hosted import HostedError, HostedStore
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from tests.acceptance.test_upload_security import pdf
from tests.test_hosted_public import actor
from tests.test_hosted_public import settings as _settings


def action_pdf(kind="/GoToR", *, trigger="click", danger=None, password=None):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    # LGES/SDI/Amore/Shinhan: /Link /A -> GoToR with indirect Filespec,
    # an InDesign destination string and optional /NewWindow false.
    filespec = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Filespec"),
                NameObject("/F"): TextStringObject("InDesign ClipboardScrap1.pdf"),
            }
        )
    )
    entries = {NameObject("/S"): NameObject(kind)}
    if kind == "/GoToR":
        entries.update(
            {
                NameObject("/F"): filespec,
                NameObject("/D"): TextStringObject("InDesign ClipboardScrap1::0"),
            }
        )
    else:
        entries[NameObject("/N")] = NameObject("/FitPage")
        entries[NameObject("/Type")] = NameObject("/Action")
    action = DictionaryObject(entries)
    if danger:
        action[NameObject("/Next")] = DictionaryObject(
            {
                NameObject("/S"): NameObject(danger),
                NameObject("/JS" if danger == "/JavaScript" else "/F"): TextStringObject(
                    "https://example.invalid/evil"
                ),
            }
        )
    action_ref = writer._add_object(action)
    annotation = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/A"): action_ref,
        }
    )
    writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    if trigger == "open":
        writer.root_object[NameObject("/OpenAction")] = action_ref
    elif trigger == "page":
        writer.pages[0][NameObject("/AA")] = DictionaryObject({NameObject("/O"): action_ref})
    if password is not None:
        writer.encrypt(password, owner_password="owner-only")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def verify(tmp_path, data, **kwargs):
    path = tmp_path / "input.pdf"
    path.write_bytes(data)
    return verify_pdf_file(
        path,
        PdfLimits(max_bytes=150 * 1024**2, max_decoded_bytes=512 * 1024**2),
        expected_size=len(data),
        expected_sha256=sha256(data).hexdigest(),
        **kwargs,
    )


@pytest.mark.parametrize("kind", ["/GoToR", "/Named"])
def test_original_click_action_shape_is_accepted(tmp_path, kind):
    assert verify(tmp_path, action_pdf(kind)) == 1


@pytest.mark.parametrize("kind", ["/GoToR", "/Named"])
@pytest.mark.parametrize(
    "trigger,danger",
    [
        ("open", None),
        ("page", None),
        ("click", "/JavaScript"),
        ("click", "/Launch"),
        ("click", "/SubmitForm"),
        ("click", "/GoToE"),
    ],
)
@pytest.mark.parametrize("password", [None, ""])
def test_shared_automatic_and_dangerous_next_remain_rejected(
    tmp_path, kind, trigger, danger, password
):
    with pytest.raises(UploadRejected, match="PDF_INVALID"):
        verify(tmp_path, action_pdf(kind, trigger=trigger, danger=danger, password=password))


def test_owner_only_encryption_produces_auditable_plain_copy(tmp_path):
    data = action_pdf(password="")
    metadata = {}
    derived = tmp_path / "decrypted.pdf"
    assert verify(tmp_path, data, derived_path=derived, security_metadata=metadata) == 1
    assert not PdfReader(derived, strict=True).is_encrypted
    assert metadata["source_sha256"] == sha256(data).hexdigest()
    assert metadata["analysis_sha256"] == sha256(derived.read_bytes()).hexdigest()
    assert metadata["encrypted"] is True
    assert (tmp_path / "input.pdf").read_bytes() == data
    # Retained actions are still classified; conversion is never a safety bypass.
    assert verify(tmp_path, derived.read_bytes()) == 1


def test_opening_password_remains_required(tmp_path):
    with pytest.raises(UploadRejected, match="PDF_PASSWORD_REQUIRED"):
        verify(tmp_path, pdf(password="secret"))


@pytest.mark.parametrize(
    "fragment,pages",
    [
        ("S-OIL", 69),
        ("SK이노베이션", 171),
        ("KT 2025", 146),
        ("HD한국조선", 202),
        ("삼성물산", 132),
    ],
)
def test_original_parser_and_node_limit_reports(tmp_path, fragment, pages):
    corpus = Path(__file__).resolve().parents[3] / "기업보고서"
    if not corpus.exists():
        pytest.skip("Local 50-report corpus is not shipped in source distribution")
    path = next(p for p in corpus.rglob("*.pdf") if fragment in normalize("NFC", p.name))
    data = path.read_bytes()
    assert verify(tmp_path, data) == pages


def test_hosted_encryption_preserves_original_and_uses_derived_for_prepare(tmp_path):
    settings = _settings.__wrapped__(tmp_path)
    store = HostedStore(settings)
    auth = actor(store)
    data = action_pdf(password="")
    document = store.upload(auth, data, "fx6b-encrypted-001", now=time.time())
    directory = store.document_dir(auth.tenant_id, document["document_id"])
    assert (directory / "original.pdf").read_bytes() == data
    metadata = json.loads((directory / "upload-security.json").read_text())
    assert metadata["source_sha256"] == document["sha256"]
    assert not PdfReader(directory / "decrypted.pdf").is_encrypted
    assert store.analysis_source(directory, document).name == "decrypted.pdf"
    replay = store.upload(auth, data, "fx6b-encrypted-001", now=time.time())
    assert replay == document
    store.create_run(auth, document["document_id"], [1], "fx6b-prepare-run01", now=time.time())
    job = store.claim(now=time.time())
    prepared = store.prepare(job, now=time.time())
    assert not PdfReader(prepared).is_encrypted
    assert len(PdfReader(prepared).pages) == 1
    scope = store.generate_scope(auth, document["document_id"])
    assert scope["plan"]["source_sha256"] == document["sha256"]
    (directory / "decrypted.pdf").chmod(0o600)
    (directory / "decrypted.pdf").write_bytes(pdf())
    with pytest.raises(HostedError, match="UPLOAD_INTEGRITY_MISMATCH"):
        store.analysis_source(directory, document)


@pytest.mark.parametrize(
    "fixture", sorted((Path(__file__).parent / "fixtures/fx6b").glob("*-click.pdf"))
)
@pytest.mark.parametrize("mixed", [False, True])
def test_copied_original_action_fixtures(tmp_path, fixture, mixed):
    data = fixture.read_bytes()
    if mixed:
        writer = PdfWriter(clone_from=PdfReader(BytesIO(data)))
        action = writer.pages[0]["/Annots"][0].get_object()["/A"]
        action[NameObject("/Next")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("evil()"),
            }
        )
        output = BytesIO()
        writer.write(output)
        with pytest.raises(UploadRejected, match="PDF_INVALID"):
            verify(tmp_path, output.getvalue())
    else:
        assert verify(tmp_path, data) == 1


@pytest.mark.parametrize(
    "fixture", sorted((Path(__file__).parent / "fixtures/fx6b").glob("*-owner-metadata.pdf"))
)
@pytest.mark.parametrize("mixed", [False, True])
def test_original_plaintext_metadata_encryption_structure(tmp_path, fixture, mixed):
    data = fixture.read_bytes()
    if mixed:
        token = b"/Subtype /XML"
        assert token in data
        data = data.replace(token, b"/JS (evil())".ljust(len(token)), 1)
        with pytest.raises(UploadRejected, match="PDF_INVALID"):
            verify(tmp_path, data)
    else:
        metadata = {}
        derived = tmp_path / "derived.pdf"
        assert verify(tmp_path, data, derived_path=derived, security_metadata=metadata) == 1
        assert not PdfReader(derived).is_encrypted
        assert metadata["source_sha256"] == sha256(data).hexdigest()


@pytest.mark.parametrize("danger", [False, True])
def test_xref_recovery_never_drops_hidden_objects(tmp_path, danger):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    # S-OIL has undefined live xref entries at offset 0. Also hide a real orphan
    # behind such an entry: recovery must retain and inspect its physical body.
    writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Action"),
                NameObject("/S"): NameObject("/JavaScript" if danger else "/Named"),
                NameObject("/JS" if danger else "/N"): TextStringObject("evil()")
                if danger
                else NameObject("/NextPage"),
            }
        )
    )
    output = BytesIO()
    writer.write(output)
    data = output.getvalue()
    match = re.search(rb"xref\n0 (\d+)\n(.*?)trailer", data, re.S)
    assert match
    count = int(match[1])
    rows = match[2].splitlines(keepends=True)
    rows[-1] = b"0000000000 00000 n \n"
    rows.append(b"0000000000 00000 n \n")
    data = (
        data[: match.start()]
        + b"xref\n0 "
        + str(count + 1).encode()
        + b"\n"
        + b"".join(rows)
        + data[match.end() - 7 :]
    )
    data = data.replace(b"/Size " + str(count).encode(), b"/Size " + str(count + 1).encode())
    if danger:
        with pytest.raises(UploadRejected, match="PDF_INVALID"):
            verify(tmp_path, data)
    else:
        metadata = {}
        assert verify(tmp_path, data, security_metadata=metadata) == 1
        assert metadata["parser_xref_recovered"] is True


def test_orion_undefined_page_destination_remains_rejected(tmp_path):
    from pypdf.generic import IndirectObject

    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.root_object[NameObject("/OpenAction")] = DictionaryObject(
        {
            NameObject("/S"): NameObject("/GoTo"),
            NameObject("/D"): ArrayObject([IndirectObject(0, 0, writer), NameObject("/Fit")]),
        }
    )
    output = BytesIO()
    writer.write(output)
    with pytest.raises(UploadRejected, match="PDF_INVALID"):
        verify(tmp_path, output.getvalue())
