from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "app" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from shared import require_successful_upload
from index_documents import _document_title


class IndexingScriptTests(unittest.TestCase):
    def test_document_title_uses_first_nonempty_line_and_code(self) -> None:
        self.assertEqual(
            _document_title(
                "e-22-onder-sp.pdf",
                "\n\nE-22 ONDER-SP\nAn energized rack",
                "E-22-onder-sp",
            ),
            "E-22-onder-sp — E-22 ONDER-SP",
        )

    def test_successful_upload_count_is_returned(self) -> None:
        results = [SimpleNamespace(succeeded=True, key="1")]
        self.assertEqual(
            require_successful_upload(results, resource_name="index"), 1
        )

    def test_partial_upload_failure_raises(self) -> None:
        results = [
            SimpleNamespace(
                succeeded=False,
                key="bad",
                error_message="invalid document",
            )
        ]
        with self.assertRaisesRegex(RuntimeError, "bad: invalid document"):
            require_successful_upload(results, resource_name="index")


if __name__ == "__main__":
    unittest.main()
