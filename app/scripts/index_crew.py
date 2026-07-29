"""
index_crew.py
One-time script: reads data/crew.json and indexes crew records into
Azure AI Search as `idx_crew`.

Requires:
  pip install azure-search-documents azure-identity python-dotenv

Usage:
  python scripts/index_crew.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    SearchableField,
)

from shared import get_search_clients, require_successful_upload, scoped_name

INDEX_NAME = scoped_name("idx_crew", "AZURE_SEARCH_CREW_INDEX")

DATA_FILE = Path(__file__).parent.parent / "data" / "crew.json"


def _ensure_index(client: SearchIndexClient) -> None:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchableField(name="crew_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="search_summary", type=SearchFieldDataType.String),
        SearchableField(name="name", type=SearchFieldDataType.String),
        SimpleField(name="personeelsnummer", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="functie", type=SearchFieldDataType.String),
        SearchField(
            name="aanwijzingen",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        SearchField(
            name="raamopdracht_ids",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        SearchableField(name="home_base", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="shift_status_demo", type=SearchFieldDataType.String, filterable=True),
    ]

    semantic_config = SemanticConfiguration(
        name="default",
        prioritized_fields=SemanticPrioritizedFields(
            content_fields=[
                SemanticField(field_name="search_summary"),
                SemanticField(field_name="name"),
                SemanticField(field_name="functie"),
            ],
            title_field=SemanticField(field_name="crew_id"),
            keywords_fields=[
                SemanticField(field_name="home_base"),
            ],
        ),
    )

    index = SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        semantic_search=SemanticSearch(configurations=[semantic_config]),
    )

    client.create_or_update_index(index)
    print(f"Index '{INDEX_NAME}' ready.")


def main() -> None:
    if not DATA_FILE.exists():
        print(f"ERROR: {DATA_FILE} not found.")
        sys.exit(1)

    index_client, search_client = get_search_clients(INDEX_NAME)
    _ensure_index(index_client)

    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    # Unwrap if nested under a top-level key
    if isinstance(records, dict):
        records = next(iter(records.values()))
    docs = []
    for crew in records:
        docs.append({
            "id": crew["crew_id"],
            "crew_id": crew["crew_id"],
            "search_summary": (
                f"Crew member {crew['crew_id']}, {crew.get('name', '')}, "
                f"has role {crew.get('functie', '')}, is linked to "
                f"authorizations {', '.join(crew.get('raamopdracht_ids', []))}, "
                f"has demo shift status {crew.get('shift_status_demo', '')}, "
                f"and home base {crew.get('home_base', '')}."
            ),
            "name": crew.get("name", ""),
            "personeelsnummer": crew.get("personeelsnummer", ""),
            "functie": crew.get("functie", ""),
            "aanwijzingen": crew.get("aanwijzingen", []),
            "raamopdracht_ids": crew.get("raamopdracht_ids", []),
            "home_base": crew.get("home_base", ""),
            "shift_status_demo": crew.get("shift_status_demo", ""),
        })

    result = search_client.upload_documents(docs)
    succeeded = require_successful_upload(result, resource_name=INDEX_NAME)
    print(f"Done. Indexed {succeeded}/{len(docs)} crew records into '{INDEX_NAME}'.")


if __name__ == "__main__":
    main()
