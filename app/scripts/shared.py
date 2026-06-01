"""
shared.py
Common helpers for the index / deploy scripts.
"""
from __future__ import annotations

import os
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

# All scripts share the repo-root .env
load_dotenv(Path(__file__).parent.parent.parent / ".env")


def get_search_credential():
    """Return an API-key credential if AZURE_SEARCH_ADMIN_KEY is set,
    otherwise fall back to DefaultAzureCredential (RBAC)."""
    key = os.getenv("AZURE_SEARCH_ADMIN_KEY")
    return AzureKeyCredential(key) if key else DefaultAzureCredential()


def get_search_clients(index_name: str) -> tuple[SearchIndexClient, SearchClient]:
    """Return (index_client, search_client) for the given index."""
    endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    credential = get_search_credential()
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    return index_client, search_client
