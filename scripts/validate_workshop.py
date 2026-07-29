#!/usr/bin/env python3
"""Offline release gate for the workshop repository."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "labs" / "azure-ai-agents"
EVAL_DIR = ROOT / "labs" / "observability-and-evaluation"

EXPECTED_NOTEBOOKS = {
    CORE_DIR: 7,
    EVAL_DIR: 7,
}

OBSOLETE_NARRATIVES = (
    "retail bank",
    "wealth management",
    "loan application",
    "credit card application",
    "fraud investigation",
)


def _source(cell: dict) -> str:
    value = cell.get("source", "")
    return "".join(value) if isinstance(value, list) else value


def _compile_notebook_code(path: Path, notebook: dict) -> list[str]:
    errors: list[str] = []
    for index, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        lines = _source(cell).splitlines()
        python_lines: list[str] = []
        skip_cell = bool(lines and lines[0].lstrip().startswith("%%"))
        if skip_cell:
            continue
        for line in lines:
            if line.lstrip().startswith(("%", "!")):
                continue
            python_lines.append(line)
        source = "\n".join(python_lines)
        try:
            compile(
                source,
                f"{path}:cell-{index}",
                "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )
        except SyntaxError as exc:
            errors.append(f"{path}: code cell {index}: {exc}")
    return errors


def validate_notebooks() -> list[str]:
    errors: list[str] = []
    for directory, expected_count in EXPECTED_NOTEBOOKS.items():
        paths = sorted(directory.glob("*.ipynb"))
        if len(paths) != expected_count:
            errors.append(
                f"{directory}: expected {expected_count} notebooks, found {len(paths)}"
            )
        for path in paths:
            try:
                notebook = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{path}: invalid JSON: {exc}")
                continue

            if notebook.get("nbformat") != 4:
                errors.append(f"{path}: expected nbformat 4")

            text = "\n".join(_source(cell) for cell in notebook.get("cells", []))
            lowered = text.lower()
            if "workshop_resource_namespace" not in lowered:
                errors.append(f"{path}: missing WORKSHOP_RESOURCE_NAMESPACE")
            if not any(
                marker in lowered
                for marker in ("participant task", "participant challenge")
            ):
                errors.append(f"{path}: missing participant task/challenge")
            if "success check" not in lowered and "assert " not in lowered:
                errors.append(f"{path}: missing deterministic success check")

            for phrase in OBSOLETE_NARRATIVES:
                if phrase in lowered:
                    errors.append(f"{path}: obsolete narrative remains: {phrase!r}")

            for index, cell in enumerate(notebook.get("cells", []), start=1):
                if cell.get("cell_type") != "code":
                    continue
                if cell.get("outputs"):
                    errors.append(f"{path}: code cell {index} has saved outputs")
                if cell.get("execution_count") is not None:
                    errors.append(
                        f"{path}: code cell {index} has an execution count"
                    )

            errors.extend(_compile_notebook_code(path, notebook))
    return errors


def validate_local_markdown_links() -> list[str]:
    errors: list[str] = []
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    paths = {
        ROOT / "README.md",
        ROOT / "app" / "README.md",
        ROOT / "app" / "data" / "README.md",
        ROOT / "setup" / "README.md",
        *sorted((ROOT / "docs").glob("*.md")),
        *sorted((ROOT / "labs").glob("*/README.md")),
    }
    for path in sorted(paths):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"`[^`]*`", "", text)
        for target in link_re.findall(text):
            target = target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                errors.append(f"{path}: broken local link: {target}")
    return errors


def main() -> int:
    errors = [
        *validate_notebooks(),
        *validate_local_markdown_links(),
    ]
    if errors:
        print("Workshop validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Workshop validation passed: notebooks, exercises, outputs, code and docs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
