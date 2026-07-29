from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from rules.evaluate_rules import CURATED_VWI_IDS, evaluate_rules


def _verdicts(proposal: dict) -> dict[str, dict]:
    return {
        item["rule_id"]: item
        for item in json.loads(evaluate_rules(proposal))
    }


class DispatchRuleTests(unittest.TestCase):
    def test_catalogue_is_derived_from_full_pdf_corpus(self) -> None:
        self.assertGreaterEqual(len(CURATED_VWI_IDS), 30)
        self.assertIn("E-04", CURATED_VWI_IDS)
        self.assertIn("E-60", CURATED_VWI_IDS)
        self.assertIn("E-85", CURATED_VWI_IDS)

    def test_ambiguous_bare_vwi_code_fails_closed(self) -> None:
        verdicts = _verdicts(
            {
                "vwis": [{"vwi_id": "E-22", "confidence": "candidate"}],
                "matched_raamopdracht_id": "RA-NHN-0102",
                "postcode": "1815 BR",
                "incident_timestamp": "2026-06-01T10:00:00",
            }
        )
        self.assertFalse(verdicts["BLS-R01"]["pass"])
        self.assertFalse(verdicts["BLS-R02"]["pass"])
        self.assertTrue(verdicts["BLS-R03"]["pass"])
        self.assertTrue(verdicts["BLS-R04"]["pass"])

    def test_iso_datetime_is_used_for_temporal_rule(self) -> None:
        verdicts = _verdicts(
            {
                "vwis": [{"vwi_id": "E-04", "confidence": "confirmed"}],
                "matched_raamopdracht_id": "RA-NHN-0104",
                "postcode": "1622 AA",
                "incident_timestamp": "2026-05-21T00:01:00+02:00",
            }
        )
        self.assertFalse(verdicts["BLS-R03"]["pass"])

    def test_invalid_timestamp_fails_temporal_rule(self) -> None:
        verdicts = _verdicts(
            {
                "vwis": [{"vwi_id": "E-04", "confidence": "confirmed"}],
                "matched_raamopdracht_id": "RA-NHN-0105",
                "postcode": "1622 AA",
                "incident_timestamp": "not-a-date",
            }
        )
        self.assertFalse(verdicts["BLS-R03"]["pass"])

    def test_live_work_requires_explicit_permission_and_coverage(self) -> None:
        verdicts = _verdicts(
            {
                "vwis": [
                    {"vwi_id": "E-22-onder-sp", "confidence": "confirmed"}
                ],
                "matched_raamopdracht_id": "RA-NHN-0101",
                "postcode": "1701 AB",
                "incident_timestamp": "2026-06-01T10:00:00",
                "requires_live_work": True,
            }
        )
        self.assertFalse(verdicts["BLS-R02"]["pass"])
        self.assertFalse(verdicts["BLS-R05"]["pass"])

    def test_unknown_vwi_fails_catalogue_gate(self) -> None:
        verdicts = _verdicts(
            {
                "vwis": [{"vwi_id": "E-99", "confidence": "candidate"}],
                "matched_raamopdracht_id": "RA-NHN-0101",
                "postcode": "1701 AB",
                "incident_timestamp": "2026-06-01T10:00:00",
            }
        )
        self.assertFalse(verdicts["BLS-R01"]["pass"])


if __name__ == "__main__":
    unittest.main()
