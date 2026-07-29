from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from workflows.dispatch import (
    _apply_deterministic_match,
    _normalize_matcher_output,
    _normalize_reviewer_output,
    _overlap_vwi_set,
)


class DispatchSafetyTests(unittest.TestCase):
    def test_ambiguous_base_does_not_overlap_variant(self) -> None:
        self.assertEqual(
            _overlap_vwi_set(["E-22"], ["E-22-onder-sp"]),
            set(),
        )

    def test_available_crew_is_respected_when_mapping_ro(self) -> None:
        proposal = {"vwis": [{"vwi_id": "E-85", "confidence": "confirmed"}]}
        ro = {
            "raamopdracht_id": "RA-NHN-0101",
            "covered_vwi_ids": ["E-85"],
        }
        result = _apply_deterministic_match(
            proposal, [ro], ["crew-002-M-Janssen"]
        )
        self.assertIsNone(result["matched_crew"])

    def test_invalid_matcher_shape_fails_closed(self) -> None:
        result = _normalize_matcher_output(["not", "an", "object"])
        self.assertTrue(result["output_parse_error"])
        self.assertEqual(result["vwis"], [])

    def test_invalid_reviewer_shape_flags_human_review(self) -> None:
        result = _normalize_reviewer_output(
            {"review_status": "pass", "findings": "not-an-array"}
        )
        self.assertEqual(result["review_status"], "flagged_for_human_review")
        self.assertEqual(result["findings"][-1]["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
