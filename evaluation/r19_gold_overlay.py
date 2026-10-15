"""V4 opt-in, additive R19/DEC-93 evaluation gold; never writes product state."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

VERSION = "v4_r19_gold_overlay_v1"
FOOTNOTES = ("kia-106-I011", "kia-106-I032", "kia-106-I033", "kia-106-I034")
SCORER_SHA256 = "edd466dbc9dfc5d14be051bd36facdb81fff5867ec3820256317584d6fe5a5ec"
POLICY = {
    "profile": VERSION,
    "scope": "surrounding original context; blank answers are not approvals",
    "footnotes": list(FOOTNOTES),
    "AP-01": "category only; grade mapping null",
    "AP-02": "forecast remains forecast; no performance/confirmation promotion",
    "AP-03": "verified same entity/metric/unit/boundary within frozen selected scope",
    "AP-04b": "inferred performance forbidden",
    "AP-05": "naver-221-P2 conflict preserved; excluded",
    "AP-06": "explicit subject/activity/target/period relation required",
    "R2": "not_run",
    "gold_approved": False,
    "production_revision_writer": False,
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Inputs:
    """Record exact read bytes, then detect concurrent changes before publishing."""

    def __init__(self):
        self.hashes = {}

    def record(self, path, expected=None):
        path = Path(path).resolve()
        actual = file_hash(path)
        if expected is not None and actual != expected:
            raise ValueError(f"SOURCE_HASH_MISMATCH: {path}")
        if str(path) in self.hashes and self.hashes[str(path)] != actual:
            raise ValueError(f"SOURCE_CHANGED: {path}")
        self.hashes[str(path)] = actual
        return actual

    def read(self, path, expected=None):
        self.record(path, expected)
        return json.loads(Path(path).read_text())

    def verify(self):
        for name, expected in list(self.hashes.items()):
            self.record(Path(name), expected)


def frozen_scorer(path, inputs):
    inputs.record(path, SCORER_SHA256)
    spec = importlib.util.spec_from_file_location("v4_frozen_dl4", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reply_provenance(reply, workbook, coverage):
    """Match every field, including blank answers, to physical worksheet cells."""
    result = []
    for section, rows in reply.items():
        sheet = workbook[section]
        headers = sheet[0]["cells"]
        for index, raw in enumerate(rows):
            source = sheet[index + 1]
            cells = {}
            for column, header in headers.items():
                value = source["cells"].get(column)
                expected = raw[header]
                if (None if expected is None else str(expected)) != value:
                    raise ValueError(f"REPLY_CELL_MISMATCH: {section}!{column}{source['row']}")
                cells[header] = {
                    "cell": f"{section}!{column}{source['row']}",
                    "value": value,
                }
            pointer = f"/{section}/{index}"
            rule = next(x for x in coverage if x["source_pointer"] == pointer)
            result.append(
                {
                    "source_pointer": pointer,
                    "raw_row": copy.deepcopy(raw),
                    "cells": cells,
                    "raw_row_sha256": digest(raw),
                    "rule_ids": rule["delta_ids"],
                    "respondent": "TEAM-20261015; individual identity not supplied",
                }
            )
    if len(result) != 46 or len(coverage) != 46:
        raise ValueError("REPLY_COVERAGE_NOT_46")
    return result


def build_overlay(gold, reply, provenance, rules, returned, source_hashes):
    if len(gold["golds"]) != 131:
        raise ValueError("DL4_DENOMINATOR_NOT_131")
    pending = [r for r in gold["rows"] if r["dl4_status"] == "pending_scope"]
    if len(pending) != 28:
        raise ValueError("DL4_PENDING_NOT_28")
    scope_rows = reply["1_범위판정"]
    if len(scope_rows) != 31 or sum(r["답"] is None for r in scope_rows) != 30:
        raise ValueError("SCOPE_REPLY_CONTRACT_CHANGED")
    actions = rules["gold_impact"]["row_actions"]
    if len(actions) != 64:
        raise ValueError("R19_QUEUE_NOT_64")
    pending_by_id = {r["ID"]: r for r in pending}
    patches = []
    for ident in FOOTNOTES:
        row = pending_by_id[ident]
        index = next(i for i, r in enumerate(scope_rows) if r["ID"] == ident)
        patches.append(
            {
                "id": ident,
                "before": "pending_scope",
                "after": "evidence_context",
                "reason": "R19-D01/DEC-92: original p106 table methodology/boundary footnote",
                "source_pointer": f"/1_범위판정/{index}",
                "gold_pointer": f"/rows/{gold['rows'].index(row)}",
                "original_quote": row["주장 원문"],
                "original_quote_sha256": digest(row["주장 원문"]),
                "source_pdf_sha256": row["PDF_SHA256"],
                "source_location": row["원문 위치"],
                "gold_cell": f"{row['excel_sheet']}!{row['excel_row']}",
                "raw_answer": scope_rows[index]["답"],
                "raw_note": scope_rows[index]["메모"],
                "answer_note_conflict_preserved": ident == "kia-106-I011",
                "adjudicator": "V4 adopts R19 original-page role review under task authorization",
                "rule_version": VERSION,
            }
        )
    tables = [
        {
            "id": "naver-221-P2",
            "role": "conflict",
            "excluded": True,
            "replacement_value": None,
            "source_pointer": "/2_표대조보류/0",
            "reason": "AP-05: reply and original date row-header conflict; no adjacent-cell swap",
        },
        {
            "id": "kia-106-P2",
            "role": "row_header+note_marker",
            "excluded": False,
            "parser_note_loss": "틀림",
            "note_marker": "1",
            "numeric_value": None,
            "source_pointer": "/2_표대조보류/1",
            "reason": "맞음 approves note-marker role, not parser fidelity",
        },
        {
            "id": "kia-106-P3",
            "role": "unit_header",
            "excluded": False,
            "header": "단위",
            "source_pointer": "/2_표대조보류/2",
            "row_units": {"배출량": "천tCO2eq", "집약도": "tCO2eq/대"},
            "reason": "header is not the actual unit; bind units separately by row",
        },
    ]
    preserved = [r for r in returned["sheets"]["6_심층요소"] if r["ID"] in {"D11-E1", "D11-E2"}]
    if {r["ID"]: r["요소ID"] for r in preserved} != {"D11-E1": "M1", "D11-E2": "M4"}:
        raise ValueError("D11_ORIGINAL_ONTOLOGY_CHANGED")
    extra = {
        "id": "v4_D11-M2",
        "claim_id": "D11",
        "element_id": "M2",
        "gold_state": "present",
        "status": "draft_source_backed_candidate",
        "source": {
            "physical_page": 26,
            "source_pdf_sha256": preserved[0]["PDF_SHA256"],
            "location": "RE100 검토 프로세스 도식 1단계 추진 내용",
            "quote": "전 사업장 중장기\n사업계획 연계한 사용량\n예측·분석",
            "quote_source": "V4 visually checked AU1/kia-26.png",
            "review": "R19-D15; AU1/kia-26.png",
        },
        "binding": "same RE100 process; actual all-worksite span, not mere four-step existence",
        "retag_required": True,
        "grade": None,
        "production_present": False,
    }
    overlay = {
        "schema": VERSION,
        "policy": POLICY,
        "policy_sha256": digest(POLICY),
        "source_hashes": copy.deepcopy(source_hashes),
        "base_gold_content_sha256": digest(gold),
        "reply_provenance": provenance,
        "scope_patches": patches,
        "table_roles": tables,
        "preserved_deep_elements": preserved,
        "new_deep_elements": [extra],
        "row_action_queue": copy.deepcopy(actions),
        "r17_retag_queue": copy.deepcopy(
            rules["gold_impact"]["r17"]["rule_affected_rows_and_recovery_cohort"]
        ),
        "scope_rule": "주변 문맥 판단; original role, not numbering or blank reply",
        "scope_rule_source": "DEC-92; not a fabricated workbook response cell",
        "pending_deep_rows": ["D01", "D03", "D05"],
        "before": {"atoms": 131, "pending_scope": 28},
        "after": {"atoms": 131, "pending_scope": 24},
        "annotation_status": "draft",
        "gold_approved": False,
        "R2": "not_run",
    }
    overlay["overlay_sha256"] = digest(overlay)
    return overlay


def apply_overlay(gold, overlay):
    """Return a derived copy. Atom identities, quotes and the original stay untouched."""
    if overlay["schema"] != VERSION or overlay["policy_sha256"] != digest(POLICY):
        raise ValueError("OVERLAY_POLICY_MISMATCH")
    if (
        digest({k: v for k, v in overlay.items() if k != "overlay_sha256"})
        != overlay["overlay_sha256"]
    ):
        raise ValueError("OVERLAY_HASH_MISMATCH")
    if digest(gold) != overlay["base_gold_content_sha256"]:
        raise ValueError("OVERLAY_BASE_GOLD_CHANGED")
    result = copy.deepcopy(gold)
    rows = {r["ID"]: r for r in result["rows"]}
    if {p["id"] for p in overlay["scope_patches"]} != set(FOOTNOTES):
        raise ValueError("OVERLAY_PATCH_IDS_CHANGED")
    for patch in overlay["scope_patches"]:
        row = rows[patch["id"]]
        if (
            row["dl4_status"] != patch["before"]
            or digest(row["주장 원문"]) != patch["original_quote_sha256"]
        ):
            raise ValueError("OVERLAY_SOURCE_ROW_MISMATCH")
        row["dl4_status"] = patch["after"]
        row["v4_overlay_sha256"] = overlay["overlay_sha256"]
    result["v4_overlay_sha256"] = overlay["overlay_sha256"]
    result["gold_approved"] = False
    result["annotation_status"] = "draft"
    return result
