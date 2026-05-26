"""
index_raamopdrachten.py
One-time script: reads data/raamopdrachten.json and indexes them into
Azure AI Search as `idx_raamopdrachten`.

Requires:
  pip install azure-search-documents azure-identity python-dotenv

Usage:
  python scripts/index_raamopdrachten.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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

from shared import get_search_clients

INDEX_NAME = os.getenv("AZURE_SEARCH_RO_INDEX", "idx_raamopdrachten")

DATA_FILE = Path(__file__).parent.parent / "data" / "raamopdrachten.json"


def _ensure_index(client: SearchIndexClient) -> None:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="raamopdracht_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="bestemd_voor", type=SearchFieldDataType.String),
        SearchField(
            name="covered_vwi_ids",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        SearchField(
            name="geldigheidsgebied_postcodes",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        SimpleField(name="geldigheidsduur_start", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="geldigheidsduur_end", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="permits_live_work", type=SearchFieldDataType.Boolean, filterable=True),
        SearchableField(name="omschrijving_bedieningshandelingen", type=SearchFieldDataType.String),
        SearchableField(name="omschrijving_werkzaamheden", type=SearchFieldDataType.String),
        SearchableField(name="bei_bls_aanwijzing", type=SearchFieldDataType.String),
        SearchableField(name="geldigheidsgebied_prose", type=SearchFieldDataType.String),
    ]

    semantic_config = SemanticConfiguration(
        name="default",
        prioritized_fields=SemanticPrioritizedFields(
            content_fields=[
                SemanticField(field_name="omschrijving_bedieningshandelingen"),
                SemanticField(field_name="omschrijving_werkzaamheden"),
            ],
            title_field=SemanticField(field_name="bestemd_voor"),
            keywords_fields=[
                SemanticField(field_name="geldigheidsgebied_prose"),
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
    docs = []
    for ro in records:
        docs.append(
            {
                "id": ro["raamopdracht_id"],
                "raamopdracht_id": ro["raamopdracht_id"],
                "bestemd_voor": ro.get("bestemd_voor", ""),
                "covered_vwi_ids": ro.get("covered_vwi_ids", []),
                "geldigheidsgebied_postcodes": ro.get("geldigheidsgebied_postcodes", []),
                "geldigheidsduur_start": ro.get("geldigheidsduur_start", ""),
                "geldigheidsduur_end": ro.get("geldigheidsduur_end", ""),
                "permits_live_work": ro.get("permits_live_work", False),
                "omschrijving_bedieningshandelingen": ro.get("omschrijving_bedieningshandelingen", ""),
                "omschrijving_werkzaamheden": ro.get("omschrijving_werkzaamheden", ""),
                "bei_bls_aanwijzing": ro.get("bei_bls_aanwijzing", ""),
                "geldigheidsgebied_prose": ro.get("geldigheidsgebied_prose", ""),
            }
        )

    result = search_client.upload_documents(docs)
    succeeded = sum(1 for r in result if r.succeeded)
    print(f"Done. Indexed {succeeded}/{len(docs)} raamopdrachten into '{INDEX_NAME}'.")


if __name__ == "__main__":
    main()
