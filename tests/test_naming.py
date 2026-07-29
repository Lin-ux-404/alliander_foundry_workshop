from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from utils.naming import scoped_name, workshop_namespace


class WorkshopNamingTests(unittest.TestCase):
    def test_namespace_is_normalized_and_bounded(self) -> None:
        with patch.dict(
            os.environ,
            {"WORKSHOP_RESOURCE_NAMESPACE": " Team 01 / North "},
            clear=True,
        ):
            self.assertEqual(workshop_namespace(), "team-01-north")
            self.assertEqual(
                scoped_name("idx_bls_corpus", "AZURE_SEARCH_INDEX"),
                "idx_bls_corpus-team-01-north",
            )

    def test_explicit_resource_name_wins(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WORKSHOP_RESOURCE_NAMESPACE": "team-01",
                "AZURE_SEARCH_INDEX": "approved-index",
            },
            clear=True,
        ):
            self.assertEqual(
                scoped_name("idx_bls_corpus", "AZURE_SEARCH_INDEX"),
                "approved-index",
            )

    def test_long_names_keep_a_stable_hash_suffix(self) -> None:
        with patch.dict(
            os.environ,
            {"WORKSHOP_RESOURCE_NAMESPACE": "team-with-a-very-long-shared-prefix-alpha"},
            clear=True,
        ):
            first = workshop_namespace()
        with patch.dict(
            os.environ,
            {"WORKSHOP_RESOURCE_NAMESPACE": "team-with-a-very-long-shared-prefix-beta"},
            clear=True,
        ):
            second = workshop_namespace()
        self.assertLessEqual(len(first), 24)
        self.assertLessEqual(len(second), 24)
        self.assertNotEqual(first, second)

    def test_non_alphanumeric_namespace_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"WORKSHOP_RESOURCE_NAMESPACE": "///"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                workshop_namespace()


if __name__ == "__main__":
    unittest.main()
