"""Native candidates first; isolated, ledger-reserved provider pages when needed.

Readability only selects candidates. Existing original-byte source readers must
still attest every claim/table; a route never grants verified or present.
"""

import io
from time import sleep

import pdfplumber
import pypdfium2 as pdfium
from proofops.adapters.parsing.mixed_routing import keep, readable
from proofops.adapters.parsing.upstage_document import candidate_batch
from proofops.application.ingest.page_recovery_policy import POLICY

TRANSIENT = {f"UPSTAGE_HTTP_{s}" for s in (429, 500, 502, 503, 504)}
STOP = {
    "UPSTAGE_HTTP_401",
    "UPSTAGE_HTTP_402",
    "UPSTAGE_HTTP_403",
    "UPSTAGE_API_KEY_IS_NOT_ALLOWED",
    "BUDGET_EXHAUSTED",
}


def native_pages(source, selected, candidates):
    # PDFminer may reject a broken document trailer while PDFium can read the
    # unchanged original. This supplies a routing hint, never a repaired proof.
    result = []
    try:
        document = pdfplumber.open(io.BytesIO(source.content))
    except Exception:
        document = None
    try:
        with pdfium.PdfDocument(source.content) as original:
            for number in selected:
                local = "\n".join(
                    b.source.raw_text
                    for batch in candidates
                    for b in batch.blocks
                    if b.source.physical_page == number and b.kind == "paragraph"
                )
                try:
                    if document is not None:
                        native = document.pages[number - 1].extract_text() or ""
                    else:
                        page = original[number - 1]
                        try:
                            text = page.get_textpage()
                            try:
                                native = text.get_text_range()
                            finally:
                                text.close()
                        finally:
                            page.close()
                    if readable(native) and readable(local):
                        result.append(number)
                except Exception:
                    continue
    finally:
        if document is not None:
            document.close()
    return result


def recover(source, profile, selected, candidates, call, *, config_hash):
    local = native_pages(source, selected, candidates)
    claims = list(profile.claim_physical_pages)
    rejected = sorted(set(selected) - set(local) - set(claims))
    ocr = rejected[: profile.mixed_ocr_max_pages]
    paid = sorted((set(claims) | set(ocr)) - set(local))
    batches = [keep(batch, local) for batch in candidates]
    failures, records, recovered = [], [], []
    stop = None
    for number in paid:
        if stop is not None:
            failures.append(dict(mode="standard", pages=[number], error_code=stop))
            continue
        for attempt in range(2):
            try:
                result, hit = call((number,), "standard")
                batch, metrics = candidate_batch(
                    source,
                    profile,
                    (number,),
                    result["raw_batches"],
                    mode="standard",
                    config_hash=config_hash,
                )
                batches.append(batch)
                records.append(
                    dict(
                        pages=[number],
                        receipt={k: v for k, v in result.items() if k != "raw_batches"},
                        raw_batches=result["raw_batches"],
                        cache_hit=hit,
                        metrics=metrics,
                    )
                )
                # A successful response without text still cannot establish absence.
                if any(b.source.raw_text.strip() for b in batch.blocks):
                    recovered.append(number)
                else:
                    failures.append(
                        dict(mode="standard", pages=[number], error_code="UPSTAGE_PAGE_UNREADABLE")
                    )
                break
            except ValueError as error:
                code = str(error)
                # No provider text/URLs/arbitrary exception messages in artifacts.
                import re

                if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", code):
                    code = "UPSTAGE_REQUEST_FAILED"
                if code in TRANSIENT and attempt == 0:
                    sleep(1)
                    continue
                failures.append(dict(mode="standard", pages=[number], error_code=code))
                if code in STOP or code.endswith("BUDGET_EXHAUSTED"):
                    stop = code
                break
    unreadable = sorted(set(selected) - set(local) - set(recovered))
    routing = dict(
        version="mixed-hx6-v1",
        claim_pages=claims,
        local_pages=local,
        rejected_native_pages=rejected,
        ocr_pages=ocr,
        provider_pages=recovered,
        unreadable_pages=unreadable,
    )
    output = dict(profile=POLICY, page_records=records, failed_batches=failures)
    return batches, routing, output


def provenance(routing, candidates, selected):
    records = []
    for number in selected:
        batches = [b for b in candidates if any(x.source.physical_page == number for x in b.blocks)]
        route = (
            "opendataloader"
            if number in routing["local_pages"]
            else ("upstage" if number in routing["provider_pages"] else "unreadable")
        )
        if any(
            b.parser_name not in {"opendataloader", "pdfplumber"}
            if route == "opendataloader"
            else not b.parser_name.startswith("upstage_async_")
            for b in batches
        ) or (route == "unreadable" and batches):
            raise ValueError("page parser routing mismatch")
        records.append(
            dict(
                physical_page=number,
                role="claim" if number in routing["claim_pages"] else "evidence_only",
                route=route,
                parser_names=sorted({b.parser_name for b in batches}),
                parser_run_ids=sorted({b.parser_run_id for b in batches}),
                state="candidate" if batches else "unreadable",
                source_confirmation="required",
            )
        )
    return records
