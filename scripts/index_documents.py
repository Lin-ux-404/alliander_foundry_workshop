"""
index_documents.py
One-time script: reads all PDFs from `docs/` and indexes them into
Azure AI Search as `idx_bls_corpus`.

Each PDF page becomes one search document with fields:
  id, vwi_code, title, excerpt, source_file, page_number, content

Requires:
  pip install azure-search-documents azure-identity pypdf python-dotenv

Usage:
  python scripts/index_documents.py
"""
from __future__ import annotations

import os
import re
import sys
from base64 import urlsafe_b64encode
from pathlib import Path

from azure.search.documents.indexes.models import (
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    SearchableField,
)

from shared import get_search_clients

try:
    from pypdf import PdfReader
except ImportError:
    print("ERROR: pypdf not installed. Run: pip install pypdf")
    sys.exit(1)

DOCS_ROOT = Path(__file__).parent.parent / "docs"
INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX", "idx_bls_corpus")
BATCH_SIZE = 50

_VWI_CODE_RE = re.compile(r"\bE-\d{2}\b", re.IGNORECASE)


def _infer_vwi_code(filename: str, text_sample: str) -> str:
    m = _VWI_CODE_RE.search(filename)
    if m:
        return m.group(0).upper()
    m = _VWI_CODE_RE.search(text_sample)
    if m:
        return m.group(0).upper()
    return ""


def _ensure_index(client: SearchIndexClient) -> None:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="vwi_code", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="excerpt", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="source_file", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="page_number", type=SearchFieldDataType.Int32, filterable=True),
    ]
    semantic = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="vwi_code")],
                ),
            )
        ]
    )
    index = SearchIndex(name=INDEX_NAME, fields=fields, semantic_search=semantic)
    client.create_or_update_index(index)
    print(f"Index '{INDEX_NAME}' ready.")


def _collect_pdfs() -> list[Path]:
    pdfs: list[Path] = []
    for path in DOCS_ROOT.rglob("*.pdf"):
        pdfs.append(path)
    return sorted(pdfs)


def _pdf_to_docs(pdf_path: Path) -> list[dict]:
    reader = PdfReader(str(pdf_path))
    docs: list[dict] = []
    rel = pdf_path.relative_to(DOCS_ROOT)
    source_file = str(rel).replace("\\", "/")

    # Use first-page text to infer title and VWI code
    first_text = (reader.pages[0].extract_text() or "")[:500] if reader.pages else ""
    vwi_code = _infer_vwi_code(pdf_path.name, first_text)
    title_line = first_text.split("\n")[0].strip()[:120] if first_text else pdf_path.stem

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()
        if not text:
            continue
        raw_id = f"{source_file}__p{page_num}"
        doc_id = urlsafe_b64encode(raw_id.encode()).decode().rstrip("=")
        docs.append(
            {
                "id": doc_id,
                "vwi_code": vwi_code,
                "title": title_line,
                "excerpt": text[:500],
                "content": text,
                "source_file": source_file,
                "page_number": page_num,
            }
        )
    return docs


def main() -> None:
    index_client, search_client = get_search_clients(INDEX_NAME)
    _ensure_index(index_client)

    pdfs = _collect_pdfs()
    if not pdfs:
        print(f"No PDFs found under {DOCS_ROOT}")
        sys.exit(1)

    print(f"Found {len(pdfs)} PDF(s). Indexing...")

    batch: list[dict] = []
    total = 0

    for pdf_path in pdfs:
        print(f"  Processing: {pdf_path.name}")
        docs = _pdf_to_docs(pdf_path)
        batch.extend(docs)

        while len(batch) >= BATCH_SIZE:
            to_upload = batch[:BATCH_SIZE]
            batch = batch[BATCH_SIZE:]
            result = search_client.upload_documents(to_upload)
            total += len(to_upload)
            print(f"    Uploaded {total} documents so far...")

    if batch:
        search_client.upload_documents(batch)
        total += len(batch)

    print(f"Done. Indexed {total} pages from {len(pdfs)} PDF(s) into '{INDEX_NAME}'.")


if __name__ == "__main__":
    main()
