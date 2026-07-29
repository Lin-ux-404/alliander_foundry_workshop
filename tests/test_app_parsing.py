from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from utils.parsing import (
    IncidentPayloadError,
    extract_anchors,
    parse_structured_input,
    try_parse_json,
)


class ParsingTests(unittest.TestCase):
    def test_json_recovery_handles_braces_in_strings_and_trailing_prose(self) -> None:
        value = try_parse_json(
            'Result: {"message": "use {carefully}", "nested": {"ok": true}} done'
        )
        self.assertEqual(value["nested"]["ok"], True)

    def test_json_recovery_skips_an_invalid_earlier_brace(self) -> None:
        value = try_parse_json('explanation {not json}; final {"ok": true}')
        self.assertEqual(value, {"ok": True})

    def test_structured_input_normalizes_postcode_and_voltage(self) -> None:
        payload = parse_structured_input(json.dumps({
            "incident_id": "INC-test",
            "received_at": "2026-05-21T08:14:00+02:00",
            "free_text_nl": "Storing in meterkast",
            "structured_anchors": {
                "postcode": "1701 ab",
                "voltage_class": "ls",
            },
            "available_crew": ["crew-001-K-de-Vries"],
        }))
        self.assertIsNotNone(payload)
        self.assertEqual(payload.anchors.postcode, "1701")
        self.assertEqual(payload.anchors.voltage_class, "LS")

    def test_malformed_structured_input_is_rejected(self) -> None:
        with self.assertRaises(IncidentPayloadError):
            parse_structured_input(json.dumps({
                "free_text_nl": "Storing",
                "structured_anchors": [],
            }))

    def test_free_text_anchor_matching_is_case_insensitive(self) -> None:
        anchors = extract_anchors("ms storing bij 1701 ab")
        self.assertEqual(anchors.voltage_class, "MS")
        self.assertEqual(anchors.postcode, "1701")


if __name__ == "__main__":
    unittest.main()
