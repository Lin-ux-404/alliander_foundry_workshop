"""
shared.py
Common helpers for the index / deploy scripts.
"""
from __future__ import annotations

import os
import re
from hashlib import sha256
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

# All scripts share the repo-root .env
load_dotenv(Path(__file__).parent.parent.parent / ".env")


def workshop_namespace() -> str:
    """Return a lowercase Azure-resource-safe namespace for the current team."""
    raw = os.getenv("WORKSHOP_RESOURCE_NAMESPACE", "")
    normalized = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower()).strip("-")
    if raw.strip() and not normalized:
        raise ValueError(
            "WORKSHOP_RESOURCE_NAMESPACE must contain a letter or digit"
        )
    if len(normalized) <= 24:
        return normalized
    digest = sha256(raw.strip().encode("utf-8")).hexdigest()[:6]
    prefix = normalized[:17].rstrip("-")
    return f"{prefix}-{digest}"


def scoped_name(base: str, env_var: str) -> str:
    """Resolve an explicit resource name or append the team namespace."""
    explicit = os.getenv(env_var)
    if explicit:
        return explicit
    namespace = workshop_namespace()
    return f"{base}-{namespace}" if namespace else base


def get_search_credential():
    """Return a Microsoft Entra credential for Azure AI Search."""
    return DefaultAzureCredential()


def get_search_clients(index_name: str) -> tuple[SearchIndexClient, SearchClient]:
    """Return (index_client, search_client) for the given index."""
    endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    credential = get_search_credential()
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    return index_client, search_client


def require_successful_upload(results, *, resource_name: str) -> int:
    """Raise when Azure AI Search reports any per-document upload failure."""
    failures = [
        result for result in results
        if not getattr(result, "succeeded", False)
    ]
    if failures:
        details = "; ".join(
            f"{getattr(result, 'key', '?')}: "
            f"{getattr(result, 'error_message', 'unknown error')}"
            for result in failures[:5]
        )
        raise RuntimeError(
            f"{len(failures)} document(s) failed to upload to "
            f"'{resource_name}': {details}"
        )
    return len(results)
