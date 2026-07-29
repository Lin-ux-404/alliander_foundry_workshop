"""
Create the optional, namespaced Foundry IQ multi-source retrieval resources.

The script uses Microsoft Entra tokens only. It expects the procedure,
raamopdrachten, and crew Search indexes to exist; ``setup_search.py
--foundry-iq`` creates and populates those indexes first.

Usage:
  python app/scripts/setup_foundry_iq.py
  python app/scripts/setup_foundry_iq.py --validate-only
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from azure.identity import DefaultAzureCredential

from shared import scoped_name


SEARCH_SCOPE = "https://search.azure.com/.default"
MANAGEMENT_SCOPE = "https://management.azure.com/.default"
CONNECTION_API_VERSION = "2025-10-01-preview"


@dataclass(frozen=True)
class KnowledgeSource:
    name: str
    index_name: str
    description: str
    source_fields: tuple[str, ...]
    search_fields: tuple[str, ...]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Provision or validate the namespaced Foundry IQ resources."
        )
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "Read and validate indexes, knowledge sources, the knowledge "
            "base, and the project MCP connection without changing Azure."
        ),
    )
    return parser.parse_args(argv)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} before provisioning Foundry IQ.")
    return value


def _request_json(
    *,
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url=url,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read()
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{method} {url} failed with HTTP {error.code}: {details}"
        ) from error
    return json.loads(raw) if raw else {}


def _source_body(source: KnowledgeSource) -> dict[str, Any]:
    return {
        "name": source.name,
        "kind": "searchIndex",
        "description": source.description,
        "searchIndexParameters": {
            "searchIndexName": source.index_name,
            "semanticConfigurationName": "default",
            "sourceDataFields": [
                {"name": field} for field in source.source_fields
            ],
            "searchFields": [
                {"name": field} for field in source.search_fields
            ],
        },
    }


def _knowledge_base_body(
    *,
    knowledge_base: str,
    foundry_account: str,
    model: str,
    output_mode: str,
    sources: Sequence[KnowledgeSource],
) -> dict[str, Any]:
    return {
        "name": knowledge_base,
        "description": (
            "Namespaced multi-source knowledge base for synthetic grid "
            "operations exercises."
        ),
        "retrievalInstructions": (
            "Use the VWI source for procedure requirements, the "
            "raamopdrachten source for authorization scope and validity, and "
            "the crew source for qualifications and demo availability. "
            "Plan multiple source-specific subqueries when a question spans "
            "those facts. Preserve exact procedure, authorization, crew and "
            "postcode identifiers from the request in the relevant subquery. "
            "Do not infer authorization scope from a crew relationship."
        ),
        "answerInstructions": (
            "Answer only from retrieved evidence, distinguish procedure from "
            "authorization and crew facts, and place at least one [ref_id:n] "
            "reference immediately after every factual sentence. Never cite "
            "a reference ID that was not retrieved. Say when evidence is "
            "missing."
        ),
        "outputMode": output_mode,
        "knowledgeSources": [{"name": source.name} for source in sources],
        "models": [
            {
                "kind": "azureOpenAI",
                "azureOpenAIParameters": {
                    "resourceUri": (
                        f"https://{foundry_account}.openai.azure.com"
                    ),
                    "deploymentId": model,
                    "modelName": model,
                },
            }
        ],
        "retrievalReasoningEffort": {"kind": "low"},
    }


def _connection_body(mcp_endpoint: str) -> dict[str, Any]:
    return {
        "properties": {
            "category": "RemoteTool",
            "target": mcp_endpoint,
            "authType": "ProjectManagedIdentity",
            "isDefault": True,
            "audience": "https://search.azure.com/",
            "group": "GenericProtocol",
            "metadata": {"ApiType": "Azure"},
        }
    }


def _named_field_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(item["name"])
        for item in value
        if isinstance(item, Mapping) and item.get("name")
    }


def _raise_validation_errors(label: str, errors: Sequence[str]) -> None:
    if errors:
        detail = "\n  - ".join(errors)
        raise RuntimeError(f"{label} validation failed:\n  - {detail}")


def _validate_index(
    source: KnowledgeSource,
    definition: Mapping[str, Any],
) -> None:
    fields = {
        str(field.get("name")): field
        for field in definition.get("fields") or []
        if isinstance(field, Mapping) and field.get("name")
    }
    errors: list[str] = []
    expected_fields = set(source.source_fields) | set(source.search_fields)
    missing = sorted(expected_fields - fields.keys())
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")

    not_retrievable = sorted(
        field
        for field in source.source_fields
        if field in fields and fields[field].get("retrievable") is not True
    )
    if not_retrievable:
        errors.append(
            "sourceDataFields must be retrievable: "
            + ", ".join(not_retrievable)
        )

    not_searchable = sorted(
        field
        for field in source.search_fields
        if field in fields and fields[field].get("searchable") is not True
    )
    if not_searchable:
        errors.append(
            "searchFields must be searchable: " + ", ".join(not_searchable)
        )

    semantic_names = {
        str(item.get("name"))
        for item in (
            (definition.get("semantic") or {}).get("configurations") or []
        )
        if isinstance(item, Mapping) and item.get("name")
    }
    if "default" not in semantic_names:
        errors.append("semantic configuration 'default' is missing")

    _raise_validation_errors(f"Index '{source.index_name}'", errors)


def _validate_source(
    source: KnowledgeSource,
    definition: Mapping[str, Any],
) -> None:
    expected = _source_body(source)
    actual_params = definition.get("searchIndexParameters") or {}
    expected_params = expected["searchIndexParameters"]
    errors: list[str] = []

    if definition.get("kind") != expected["kind"]:
        errors.append(
            f"kind is {definition.get('kind')!r}, expected {expected['kind']!r}"
        )
    for property_name in (
        "searchIndexName",
        "semanticConfigurationName",
    ):
        if actual_params.get(property_name) != expected_params[property_name]:
            errors.append(
                f"{property_name} is {actual_params.get(property_name)!r}, "
                f"expected {expected_params[property_name]!r}"
            )

    for property_name in ("sourceDataFields", "searchFields"):
        actual_fields = _named_field_set(actual_params.get(property_name))
        expected_fields = _named_field_set(
            expected_params.get(property_name)
        )
        if actual_fields != expected_fields:
            errors.append(
                f"{property_name} is {sorted(actual_fields)!r}, "
                f"expected {sorted(expected_fields)!r}"
            )

    _raise_validation_errors(f"Knowledge source '{source.name}'", errors)


def _validate_knowledge_base(
    definition: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    errors: list[str] = []
    for property_name in (
        "outputMode",
        "retrievalInstructions",
        "answerInstructions",
    ):
        if definition.get(property_name) != expected[property_name]:
            errors.append(f"{property_name} differs from repository config")

    actual_sources = {
        str(item.get("name"))
        for item in definition.get("knowledgeSources") or []
        if isinstance(item, Mapping) and item.get("name")
    }
    expected_sources = {
        str(item["name"]) for item in expected["knowledgeSources"]
    }
    if actual_sources != expected_sources:
        errors.append(
            f"knowledgeSources is {sorted(actual_sources)!r}, "
            f"expected {sorted(expected_sources)!r}"
        )

    actual_effort = (
        definition.get("retrievalReasoningEffort") or {}
    ).get("kind")
    expected_effort = expected["retrievalReasoningEffort"]["kind"]
    if actual_effort != expected_effort:
        errors.append(
            f"retrievalReasoningEffort.kind is {actual_effort!r}, "
            f"expected {expected_effort!r}"
        )

    actual_models = definition.get("models") or []
    if len(actual_models) != 1:
        errors.append(
            f"models contains {len(actual_models)} entries, expected one"
        )
    else:
        actual_model = actual_models[0]
        expected_model = expected["models"][0]
        if actual_model.get("kind") != expected_model["kind"]:
            errors.append(
                f"model kind is {actual_model.get('kind')!r}, "
                f"expected {expected_model['kind']!r}"
            )
        actual_parameters = (
            actual_model.get("azureOpenAIParameters") or {}
        )
        expected_parameters = expected_model["azureOpenAIParameters"]
        for property_name in (
            "resourceUri",
            "deploymentId",
            "modelName",
        ):
            if (
                actual_parameters.get(property_name)
                != expected_parameters[property_name]
            ):
                errors.append(
                    f"model {property_name} is "
                    f"{actual_parameters.get(property_name)!r}, expected "
                    f"{expected_parameters[property_name]!r}"
                )

    _raise_validation_errors(
        f"Knowledge base '{expected['name']}'",
        errors,
    )


def _validate_connection(
    connection_name: str,
    definition: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    actual_properties = definition.get("properties") or {}
    expected_properties = expected["properties"]
    errors: list[str] = []
    for property_name in (
        "category",
        "target",
        "authType",
        "isDefault",
        "audience",
        "group",
    ):
        if (
            actual_properties.get(property_name)
            != expected_properties[property_name]
        ):
            errors.append(
                f"{property_name} is "
                f"{actual_properties.get(property_name)!r}, expected "
                f"{expected_properties[property_name]!r}"
            )
    _raise_validation_errors(
        f"Project MCP connection '{connection_name}'",
        errors,
    )


def _knowledge_sources() -> tuple[KnowledgeSource, ...]:
    return (
        KnowledgeSource(
            name=scoped_name(
                "bls-knowledge-source", "FOUNDRY_IQ_PROCEDURES_SOURCE"
            ),
            index_name=scoped_name(
                "idx_bls_corpus", "FOUNDRY_IQ_PROCEDURES_INDEX"
            ),
            description="VWI procedure knowledge for synthetic workshop cases.",
            source_fields=(
                "title",
                "content",
                "source_file",
                "page_number",
                "vwi_code",
            ),
            search_fields=("title", "content", "excerpt", "vwi_code"),
        ),
        KnowledgeSource(
            name=scoped_name(
                "raamopdrachten-knowledge-source",
                "FOUNDRY_IQ_RAAMOPDRACHTEN_SOURCE",
            ),
            index_name=scoped_name(
                "idx_raamopdrachten",
                "FOUNDRY_IQ_RAAMOPDRACHTEN_INDEX",
            ),
            description=(
                "Synthetic authorization scopes and procedure coverage."
            ),
            source_fields=(
                "raamopdracht_id",
                "lookup_text",
                "search_summary",
                "bestemd_voor",
                "covered_vwi_ids",
                "geldigheidsgebied_postcodes",
                "geldigheidsduur_start",
                "geldigheidsduur_end",
                "permits_live_work",
                "omschrijving_bedieningshandelingen",
                "omschrijving_werkzaamheden",
                "bei_bls_aanwijzing",
                "geldigheidsgebied_prose",
            ),
            search_fields=(
                "lookup_text",
                "search_summary",
                "bestemd_voor",
                "omschrijving_bedieningshandelingen",
                "omschrijving_werkzaamheden",
                "bei_bls_aanwijzing",
                "geldigheidsgebied_prose",
            ),
        ),
        KnowledgeSource(
            name=scoped_name(
                "crew-knowledge-source", "FOUNDRY_IQ_CREW_SOURCE"
            ),
            index_name=scoped_name("idx_crew", "FOUNDRY_IQ_CREW_INDEX"),
            description="Synthetic crew qualifications and availability.",
            source_fields=(
                "crew_id",
                "search_summary",
                "name",
                "personeelsnummer",
                "functie",
                "aanwijzingen",
                "raamopdracht_ids",
                "home_base",
                "shift_status_demo",
            ),
            search_fields=(
                "crew_id",
                "search_summary",
                "name",
                "functie",
                "home_base",
            ),
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    search_endpoint = _required("AZURE_SEARCH_ENDPOINT").rstrip("/")
    project_resource_id = _required("FOUNDRY_PROJECT_RESOURCE_ID")
    foundry_account = _required("FOUNDRY_ACCOUNT_NAME")
    api_version = os.getenv(
        "FOUNDRY_IQ_API_VERSION", "2026-05-01-preview"
    )
    knowledge_base = scoped_name(
        "grid-operations-kb", "FOUNDRY_IQ_KNOWLEDGE_BASE"
    )
    connection_name = scoped_name(
        "grid-operations-kb-connection",
        "FOUNDRY_IQ_MCP_CONNECTION_NAME",
    )
    model = os.getenv("FOUNDRY_IQ_MODEL", "gpt-4.1-mini")
    output_mode = os.getenv(
        "FOUNDRY_IQ_OUTPUT_MODE", "extractiveData"
    ).strip()
    if output_mode not in {"extractiveData", "answerSynthesis"}:
        raise ValueError(
            "FOUNDRY_IQ_OUTPUT_MODE must be extractiveData or "
            "answerSynthesis."
        )
    sources = _knowledge_sources()

    credential = DefaultAzureCredential()
    search_token = credential.get_token(SEARCH_SCOPE).token
    management_token = credential.get_token(MANAGEMENT_SCOPE).token

    for source in sources:
        index_url = (
            f"{search_endpoint}/indexes/{quote(source.index_name, safe='')}"
            f"?api-version={api_version}"
        )
        index_definition = _request_json(
            method="GET",
            url=index_url,
            token=search_token,
        )
        _validate_index(source, index_definition)

        source_url = (
            f"{search_endpoint}/knowledgesources/"
            f"{quote(source.name, safe='')}?api-version={api_version}"
        )
        if not args.validate_only:
            _request_json(
                method="PUT",
                url=source_url,
                token=search_token,
                body=_source_body(source),
            )
        source_definition = _request_json(
            method="GET",
            url=source_url,
            token=search_token,
        )
        _validate_source(source, source_definition)
        print(
            f"Knowledge source '{source.name}' "
            f"{'validated' if args.validate_only else 'ready'} "
            f"(index: {source.index_name})."
        )

    knowledge_base_url = (
        f"{search_endpoint}/knowledgebases/"
        f"{quote(knowledge_base, safe='')}?api-version={api_version}"
    )
    knowledge_base_body = _knowledge_base_body(
        knowledge_base=knowledge_base,
        foundry_account=foundry_account,
        model=model,
        output_mode=output_mode,
        sources=sources,
    )
    if not args.validate_only:
        _request_json(
            method="PUT",
            url=knowledge_base_url,
            token=search_token,
            body=knowledge_base_body,
        )
    knowledge_base_definition = _request_json(
        method="GET",
        url=knowledge_base_url,
        token=search_token,
    )
    _validate_knowledge_base(
        knowledge_base_definition,
        knowledge_base_body,
    )
    print(
        f"Knowledge base '{knowledge_base}' "
        f"{'validated' if args.validate_only else 'ready'} "
        f"with {len(sources)} knowledge sources."
    )

    mcp_endpoint = f"{knowledge_base_url.rsplit('?', 1)[0]}/mcp?api-version={api_version}"
    connection_url = (
        "https://management.azure.com"
        f"{project_resource_id}/connections/"
        f"{quote(connection_name, safe='')}"
        f"?api-version={CONNECTION_API_VERSION}"
    )
    connection_body = _connection_body(mcp_endpoint)
    if not args.validate_only:
        _request_json(
            method="PUT",
            url=connection_url,
            token=management_token,
            body=connection_body,
        )
    connection_definition = _request_json(
        method="GET",
        url=connection_url,
        token=management_token,
    )
    _validate_connection(
        connection_name,
        connection_definition,
        connection_body,
    )
    print(
        f"Project MCP connection '{connection_name}' "
        f"{'validated' if args.validate_only else 'ready'}."
    )


if __name__ == "__main__":
    main()
