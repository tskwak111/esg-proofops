"""Portable V4 overlay regressions; fixture rows are synthetic, not accuracy data."""

import copy
import tempfile
import unittest
from pathlib import Path

from evaluation.r19_gold_overlay import (
    FOOTNOTES,
    Inputs,
    apply_overlay,
    build_overlay,
    digest,
    frozen_scorer,
    reply_provenance,
)


def fixture_data():
    ids = [*FOOTNOTES, *[f"pending-{i}" for i in range(24)]]
    reply = {
        "1_범위판정": [
            {
                "ID": ident,
                "답": "주장" if index == 0 else None,
                "메모": "각주라면 근거 설명" if index == 0 else None,
            }
            for index, ident in enumerate([*ids, "D01", "D03", "D05"])
        ],
        "2_표대조보류": [
            {"ID": ident, "답": answer}
            for ident, answer in (
                ("naver-221-P2", "틀림"),
                ("kia-106-P2", "맞음"),
                ("kia-106-P3", "맞음"),
            )
        ],
        "3_DEC24사후확인": [{"번호": i, "답": "수정필요"} for i in range(6)],
        "4_해석확인": [{"구분": x, "답": "동의"} for x in "abcde"],
        "5_선택_R2검수": [{"가능 여부": "어려움"}],
    }
    coverage, workbook = [], {}
    for sheet, rows in reply.items():
        headers = {chr(65 + i): key for i, key in enumerate(rows[0])}
        workbook[sheet] = [{"row": 1, "cells": headers}]
        for index, row in enumerate(rows):
            cells = {
                column: str(row[key]) for column, key in headers.items() if row[key] is not None
            }
            workbook[sheet].append({"row": index + 2, "cells": cells})
            coverage.append({"source_pointer": f"/{sheet}/{index}", "delta_ids": ["R19-D01"]})
    gold = {
        "golds": [{"id": f"atom-{i}", "quote": f"claim-{i}"} for i in range(131)],
        "rows": [
            {
                "ID": ident,
                "dl4_status": "pending_scope",
                "주장 원문": f"source {ident}",
                "PDF_SHA256": "a" * 64,
                "원문 위치": "p106 table footnote",
                "excel_sheet": "gold",
                "excel_row": i + 2,
            }
            for i, ident in enumerate(ids)
        ],
        "gold_approved": False,
        "annotation_status": "draft",
    }
    rules = {
        "reply_coverage": coverage,
        "gold_impact": {
            "row_actions": [{"row_id": str(i)} for i in range(64)],
            "r17": {"rule_affected_rows_and_recovery_cohort": [{"rescore_mode": "retag_required"}]},
        },
    }
    returned = {
        "sheets": {
            "6_심층요소": [
                {"ID": "D11-E1", "요소ID": "M1", "PDF_SHA256": "a" * 64, "state": "present"},
                {"ID": "D11-E2", "요소ID": "M4", "PDF_SHA256": "a" * 64, "state": "present"},
            ]
        }
    }
    return gold, reply, workbook, rules, returned


def overlay_fixture():
    gold, reply, workbook, rules, returned = fixture_data()
    provenance = reply_provenance(reply, workbook, rules["reply_coverage"])
    return gold, build_overlay(gold, reply, provenance, rules, returned, {})


class TestR19Overlay(unittest.TestCase):
    def test_all_46_rows_and_blank_cells_trace_to_workbook(self):
        _, reply, workbook, rules, _ = fixture_data()
        rows = reply_provenance(reply, workbook, rules["reply_coverage"])
        self.assertEqual(46, len(rows))
        self.assertEqual(46, len({r["source_pointer"] for r in rows}))
        self.assertEqual("1_범위판정!B2", rows[0]["cells"]["답"]["cell"])
        self.assertIsNone(rows[1]["cells"]["답"]["value"])
        self.assertEqual(30, sum(r["raw_row"]["답"] is None for r in rows[:31]))

    def test_changed_answer_is_not_silently_accepted(self):
        _, reply, workbook, rules, _ = fixture_data()
        workbook["1_범위판정"][2]["cells"]["B"] = "승인"
        with self.assertRaisesRegex(ValueError, "REPLY_CELL_MISMATCH"):
            reply_provenance(reply, workbook, rules["reply_coverage"])

    def test_only_four_context_roles_change_and_gold_atoms_are_immutable(self):
        gold, overlay = overlay_fixture()
        before = copy.deepcopy(gold)
        after = apply_overlay(gold, overlay)
        self.assertEqual(before, gold)
        self.assertEqual(gold["golds"], after["golds"])
        self.assertEqual(131, len(after["golds"]))
        self.assertEqual(24, sum(r["dl4_status"] == "pending_scope" for r in after["rows"]))
        self.assertEqual(
            set(FOOTNOTES),
            {r["ID"] for r in after["rows"] if r["dl4_status"] == "evidence_context"},
        )
        self.assertFalse(after["gold_approved"])
        self.assertEqual("draft", after["annotation_status"])
        self.assertEqual(["D01", "D03", "D05"], overlay["pending_deep_rows"])
        self.assertEqual("not_run", overlay["R2"])
        self.assertTrue(overlay["scope_patches"][0]["answer_note_conflict_preserved"])

    def test_table_role_approval_does_not_repair_parser_or_replace_naver_cell(self):
        _, overlay = overlay_fixture()
        naver, note, unit = overlay["table_roles"]
        self.assertEqual("conflict", naver["role"])
        self.assertTrue(naver["excluded"])
        self.assertIsNone(naver["replacement_value"])
        self.assertEqual("틀림", note["parser_note_loss"])
        self.assertIsNone(note["numeric_value"])
        self.assertEqual("unit_header", unit["role"])
        self.assertNotEqual(unit["row_units"]["배출량"], unit["row_units"]["집약도"])

    def test_d11_m4_preserved_and_new_m2_is_separate_without_grade(self):
        _, overlay = overlay_fixture()
        self.assertEqual("M4", overlay["preserved_deep_elements"][1]["요소ID"])
        row = overlay["new_deep_elements"][0]
        self.assertEqual("v4_D11-M2", row["id"])
        self.assertEqual("M2", row["element_id"])
        self.assertTrue(row["retag_required"])
        self.assertFalse(row["production_present"])
        self.assertIsNone(row["grade"])
        self.assertEqual(64, len(overlay["row_action_queue"]))

    def test_full_base_gold_identity_is_checked(self):
        gold, overlay = overlay_fixture()
        gold["golds"][0]["quote"] = "different company or edition"
        with self.assertRaisesRegex(ValueError, "OVERLAY_BASE_GOLD_CHANGED"):
            apply_overlay(gold, overlay)

    def test_overlay_hash_detects_unapproved_patch(self):
        gold, overlay = overlay_fixture()
        overlay["scope_patches"][0]["after"] = "environment_claim"
        with self.assertRaisesRegex(ValueError, "OVERLAY_HASH_MISMATCH"):
            apply_overlay(gold, overlay)

    def test_legacy_156_is_not_dl4(self):
        gold, reply, _, rules, returned = fixture_data()
        gold["golds"].extend([{}] * 25)
        with self.assertRaisesRegex(ValueError, "DL4_DENOMINATOR_NOT_131"):
            build_overlay(gold, reply, [], rules, returned, {})

    def test_inputs_detect_concurrent_change_and_frozen_scorer_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text("{}")
            inputs = Inputs()
            inputs.read(path)
            path.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                inputs.verify()
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                frozen_scorer(path, Inputs())

    def test_policy_hash_has_task_prefix_and_dec93_boundaries(self):
        _, overlay = overlay_fixture()
        self.assertTrue(overlay["policy"]["profile"].startswith("v4_"))
        self.assertEqual(digest(overlay["policy"]), overlay["policy_sha256"])
        self.assertIn("null", overlay["policy"]["AP-01"])
        self.assertIn("forbidden", overlay["policy"]["AP-04b"])
        self.assertIn("forecast remains forecast", overlay["policy"]["AP-02"])


if __name__ == "__main__":
    unittest.main()
