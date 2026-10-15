"""Same-input regression gates; synthetic cases are not model accuracy results."""

import copy
import unittest
from types import SimpleNamespace

from evaluation.r19_gold_overlay import digest
from evaluation.r19_rescore import compare, grade_counts, validate_candidate
from tests.unit.test_r19_gold_overlay import overlay_fixture


def fixtures():
    ref = {"document_version_id": "doc-a", "quote": "same original", "page_num": 1}
    claim = {
        "claim_id": "c1",
        "quote": "same original",
        "source_refs": [ref],
        "confirmed_grade": None,
        "provisional_grade": {"display_type": "hold"},
    }
    row = {
        "case": "lg",
        "claim_id": "c1",
        "public_claim": claim,
        "element_states": {"M1": "present", "M2": "unknown"},
    }
    identity = {
        "scopes": {"kia": {"pages": [106]}},
        "document_versions": {name: [["kia", "doc-a"]] for name in ("dl4", "holdout")},
    }
    pred = {
        "schema": "v4_frozen_predictions_v1",
        "label": "synthetic",
        "input_identity": identity,
        "input_identity_sha256": digest(identity),
        "cohorts": {
            "r17": [row],
            **{
                name: [
                    {
                        "id": "p1",
                        "company": "kia",
                        "page": 106,
                        "quote": "same original",
                        "source_ref": copy.deepcopy(ref),
                    }
                ]
                for name in ("dl4", "holdout")
            },
        },
    }
    audit = {
        "reports": [
            {
                "rows": [
                    {
                        "record_type": "claim",
                        "case": "lg",
                        "claim_id": "c1",
                        "elements": [
                            {"element_id": "M1", "gold_state": "present", "scored": True},
                            {"element_id": "M2", "gold_state": "unknown", "scored": True},
                        ],
                    }
                ]
            }
        ]
    }
    return audit, pred


def comparison(candidate=None):
    audit, baseline = fixtures()
    gold, overlay = overlay_fixture()
    # The matcher is frozen and exercised on actual cohorts by the CLI. This stub
    # isolates semantic gates and never supplies model/grade evidence.
    scorer = SimpleNamespace(
        evaluate=lambda g, p: {
            "gold_denominator": len(g),
            "predictions": len(p),
            "matches": len(p),
            "recall": len(p) / len(g),
            "precision": 1.0 if p else None,
        }
    )
    return compare(audit, gold, [{}], overlay, baseline, candidate or baseline, scorer)


class TestR19Policy(unittest.TestCase):
    def test_same_saved_input_no_new_votes_or_confirmations(self):
        result = comparison()
        self.assertTrue(result["quality_gate"]["passed"])
        self.assertEqual(0, result["r17"]["after"]["grades"]["confirmed"])
        self.assertEqual(1, result["r17"]["after"]["grades"]["hold"])
        self.assertEqual([], result["r17"]["delta"]["recovered_present"])
        for name in ("dl4", "holdout"):
            metrics = result[name]["after"]["grade_and_element_metrics"]
            self.assertEqual("not_run", metrics["status"])
            self.assertIsNone(metrics["false_confirmed"])
        self.assertFalse(result["model_improvement_claim"])

    def test_new_false_present_fails_with_row_evidence(self):
        _, candidate = fixtures()
        candidate["cohorts"]["r17"][0]["element_states"]["M2"] = "present"
        result = comparison(candidate)
        self.assertFalse(result["quality_gate"]["passed"])
        self.assertEqual("M2", result["r17"]["delta"]["new_false_present"][0]["element"])

    def test_positive_loss_cannot_hide_behind_net_counts(self):
        _, candidate = fixtures()
        candidate["cohorts"]["r17"][0]["element_states"].update(M1="unknown", M2="present")
        result = comparison(candidate)
        self.assertFalse(result["quality_gate"]["no_lost_present"])
        self.assertFalse(result["quality_gate"]["no_new_false_present"])

    def test_new_confirmation_requires_adjudication_not_lower_bound_gold(self):
        for field in ("confirmed_grade", "sc1_confirmation"):
            with self.subTest(field=field):
                _, candidate = fixtures()
                candidate["cohorts"]["r17"][0]["public_claim"][field] = {"evidence_grade": "E3"}
                result = comparison(candidate)
                self.assertFalse(result["quality_gate"]["passed"])
                grades = result["r17"]["after"]["grades"]
                self.assertEqual(1, grades["confirmed"])
                self.assertIsNone(grades["false_confirmed"])
                self.assertEqual(1, grades["unadjudicated_confirmations"])

    def test_source_identity_selected_scope_and_edition_substitution_rejected(self):
        for mutation, error in (
            (lambda p: p["input_identity"]["scopes"]["kia"]["pages"].append(107), "COHORT_INPUT"),
            (
                lambda p: p["cohorts"]["dl4"][0]["source_ref"].update(document_version_id="other"),
                "PREDICTION_DOCUMENT",
            ),
            (lambda p: p["cohorts"]["dl4"][0].update(page=107), "OUTSIDE_SELECTED_SCOPE"),
            (
                lambda p: p["cohorts"]["r17"][0]["public_claim"].update(quote="other"),
                "QUOTE_CHANGED",
            ),
        ):
            with self.subTest(error=error):
                _, baseline = fixtures()
                candidate = copy.deepcopy(baseline)
                mutation(candidate)
                with self.assertRaisesRegex(ValueError, error):
                    validate_candidate(candidate, baseline)

    def test_fixed_sample_shrink_duplicate_and_unknown_states_rejected(self):
        for mutation, error in (
            (lambda p: p["cohorts"]["r17"].clear(), "COHORT_SHRANK"),
            (lambda p: p["cohorts"]["dl4"].append(p["cohorts"]["dl4"][0]), "DUPLICATE"),
            (
                lambda p: p["cohorts"]["r17"][0]["element_states"].update(M1="failed_api"),
                "INVALID_ELEMENT_STATE",
            ),
            (lambda p: p["cohorts"]["r17"][0]["element_states"].pop("M1"), "ELEMENT_COHORT"),
        ):
            with self.subTest(error=error):
                _, baseline = fixtures()
                candidate = copy.deepcopy(baseline)
                mutation(candidate)
                with self.assertRaisesRegex(ValueError, error):
                    validate_candidate(candidate, baseline)

    def test_hold_provisional_scope_confirmed_are_disjoint(self):
        _, baseline = fixtures()
        row = baseline["cohorts"]["r17"][0]
        provisional = copy.deepcopy(row)
        provisional["public_claim"]["provisional_grade"] = {"evidence_grade": "E1"}
        confirmed = copy.deepcopy(provisional)
        confirmed["public_claim"]["sc1_confirmation"] = {"evidence_grade": "E1"}
        counts = grade_counts([row, provisional, confirmed])
        self.assertEqual(
            (1, 1, 1, 1),
            tuple(counts[k] for k in ("hold", "provisional", "confirmed", "scope_confirmed")),
        )


if __name__ == "__main__":
    unittest.main()
