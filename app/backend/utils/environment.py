"""Load the workshop environment before module-level configuration is resolved."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]


def load_workshop_environment() -> None:
    """Load generated settings from deterministic repository locations.

    The deployment writes both files with the same values. Loading the
    repository-root file first also supports scripts and direct module imports;
    an already-set process environment always wins.
    """
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    load_dotenv(BACKEND_ROOT / ".env", override=False)


load_workshop_environment()
