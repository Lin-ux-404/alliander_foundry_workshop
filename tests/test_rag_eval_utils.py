from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "labs"
    / "observability-and-evaluation"
    / "rag_eval_utils.py"
)
SPEC = importlib.util.spec_from_file_location("rag_eval_utils", MODULE_PATH)
assert SPEC and SPEC.loader
rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rag)


class RagEvalUtilsTests(unittest.TestCase):
    def test_versioned_dataset_contract(self) -> None:
        path = MODULE_PATH.parent / "data" / "rag-evaluation-cases-v1.json"
        metadata, search_cases = rag.load_cases(path, "azure_ai_search")
        _, iq_cases = rag.load_cases(path, "foundry_iq")

        self.assertEqual(metadata["dataset_id"], "synthetic-grid-rag-e2e-v1")
        self.assertEqual(len(search_cases), 3)
        self.assertEqual(len(iq_cases), 2)
        self.assertTrue(
            all(
                set(case["source_filters"])
                == {"procedure", "authorization", "crew"}
                for case in iq_cases
            )
        )

    def test_iq_dataset_contract_requires_all_source_filters(self) -> None:
        payload = {
            "schema_version": "1.0",
            "cases": [
                {
                    "case_id": "IQ-INCOMPLETE",
                    "target": "foundry_iq",
                    "query": "A synthetic query",
                    "ground_truth": "A synthetic answer",
                    "expected_evidence_groups": [
                        {"name": "procedure", "any_of": ["E-85"]}
                    ],
                    "source_filters": {
                        "procedure": "vwi_code eq 'E-85'",
                        "authorization": "id eq 'RA-1'",
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "crew"):
                rag.load_cases(path, "foundry_iq")

    def test_group_recall_accepts_equivalent_keys(self) -> None:
        result = rag.retrieval_recall(
            [
                {"name": "procedure", "any_of": ["E-85", "e85"]},
                {"name": "crew", "any_of": ["crew-001-K-de-Vries"]},
            ],
            {"e-85", "CREW-001-k-de-vries"},
        )

        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["matched_groups"], 2)

    def test_document_identity_does_not_leak_relationship_keys(self) -> None:
        crew = {
            "id": "crew-001-K-de-Vries",
            "crew_id": "crew-001-K-de-Vries",
            "raamopdracht_ids": ["RA-NHN-0101"],
        }
        authorization = {
            "id": "RA-NHN-0101",
            "raamopdracht_id": "RA-NHN-0101",
            "covered_vwi_ids": ["E-85"],
        }

        self.assertEqual(
            rag.document_evidence_keys(crew),
            {"crew-001-k-de-vries"},
        )
        self.assertEqual(
            rag.document_evidence_keys(authorization),
            {"ra-nhn-0101"},
        )

    def test_citation_metrics_distinguish_coverage_and_validity(self) -> None:
        answer = (
            "The first claim is supported. [S1]\n"
            "The second claim has no citation.\n"
            "The third claim cites an unknown source. [S9]"
        )
        result = rag.citation_metrics(answer, {"S1", "S2"})

        self.assertEqual(result["factual_units"], 3)
        self.assertEqual(result["coverage"], 2 / 3)
        self.assertEqual(result["valid_coverage"], 1 / 3)
        self.assertEqual(result["validity"], 0.5)
        self.assertEqual(result["invalid_citations"], ["s9"])
        self.assertEqual(
            [claim["status"] for claim in result["claims"]],
            ["resolved", "uncited", "unresolved"],
        )

    def test_iq_citation_ids_accept_raw_reference_ids(self) -> None:
        result = rag.validate_cited_answer(
            "The authorization is active. [ref_id:7]",
            {"7"},
        )

        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["valid_coverage"], 1.0)
        self.assertEqual(result["validity"], 1.0)
        self.assertEqual(result["claims"][0]["valid_citation_ids"], ["ref_id:7"])

    def test_render_cited_answer_emits_inline_references(self) -> None:
        result = rag.validate_cited_answer(
            "The first claim is supported. [ref_id:1]\n"
            "The second claim has no citation.",
            {"1"},
        )
        rendered = rag.render_cited_answer(result)

        self.assertIn("- The first claim is supported. [ref_id:1]", rendered)
        self.assertIn("- The second claim has no citation.", rendered)

    def test_structured_cited_answer_round_trips_for_generation(self) -> None:
        result = rag.validate_cited_answer(
            {
                "claims": [
                    {
                        "text": "The authorization covers E-85.",
                        "source_ids": ["ref_id:2"],
                    },
                    {
                        "text": "The crew is available.",
                        "source_ids": ["ref_id:9"],
                    },
                ],
                "insufficient_evidence": ["The required permit was not found."],
            },
            {"2"},
        )

        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["valid_coverage"], 0.5)
        self.assertEqual(result["invalid_citations"], ["ref_id:9"])
        self.assertEqual(
            result["insufficient_evidence"],
            ["The required permit was not found."],
        )
        self.assertEqual(
            rag.render_cited_answer(result),
            "- The authorization covers E-85. [ref_id:2]\n"
            "- The crew is available. [ref_id:9]",
        )

    def test_iq_activity_metrics_keep_cost_dimensions_separate(self) -> None:
        result = rag.iq_activity_metrics(
            [
                {
                    "type": "modelQueryPlanning",
                    "inputTokens": 100,
                    "outputTokens": 10,
                    "elapsedMs": 50,
                },
                {"type": "searchIndex", "elapsedMs": 20},
                {"type": "searchIndex", "elapsedMs": 30},
                {
                    "type": "modelAnswerSynthesis",
                    "inputTokens": 200,
                    "outputTokens": 40,
                    "elapsedMs": 80,
                },
                {"type": "agenticReasoning", "reasoningTokens": 500},
            ]
        )
        self.assertEqual(
            result,
            {
                "model_input_tokens": 300,
                "model_output_tokens": 50,
                "agentic_retrieval_tokens": 500,
                "semantic_requests": 2,
                "query_planning_ms": 50,
                "search_execution_ms_sum": 50,
                "answer_synthesis_ms": 80,
            },
        )

    def test_response_usage_can_exclude_search_requests(self) -> None:
        class Usage:
            input_tokens = 120
            output_tokens = 30

        class Response:
            usage = Usage()

        result = rag.response_token_usage(Response(), semantic_requests=0)

        self.assertEqual(result["model_input_tokens"], 120)
        self.assertEqual(result["model_output_tokens"], 30)
        self.assertEqual(result["semantic_requests"], 0)

    def test_iq_context_preserves_structured_grounding_fields(self) -> None:
        context = rag.format_iq_context(
            [
                {
                    "ref_id": "4",
                    "source_name": "authorization-source",
                    "doc_key": "RA-NHN-0101",
                    "document": {
                        "raamopdracht_id": "RA-NHN-0101",
                        "covered_vwi_ids": ["E-85"],
                        "geldigheidsgebied_postcodes": ["1704"],
                        "geldigheidsduur_start": "2026-01-01",
                        "geldigheidsduur_end": "2026-12-31",
                        "permits_live_work": False,
                    },
                }
            ]
        )

        self.assertIn("raamopdracht_id: \"RA-NHN-0101\"", context)
        self.assertIn('covered_vwi_ids: [\"E-85\"]', context)
        self.assertIn('geldigheidsgebied_postcodes: [\"1704\"]', context)
        self.assertIn("permits_live_work: false", context)

    def test_iq_reference_resolution_prefers_inline_source_data(self) -> None:
        class MustNotFetch:
            def get_document(self, *, key: str) -> dict:
                raise AssertionError(f"unexpected fallback fetch for {key}")

        resolved = rag.fetch_iq_reference_documents(
            {
                "activity": [
                    {
                        "type": "searchIndex",
                        "id": 3,
                        "knowledgeSourceName": "crew-source",
                    }
                ],
                "references": [
                    {
                        "type": "searchIndex",
                        "id": "7",
                        "activitySource": 3,
                        "docKey": "crew-001",
                        "sourceData": {
                            "id": "crew-001",
                            "crew_id": "crew-001",
                        },
                    }
                ],
            },
            {"crew-source": MustNotFetch()},
        )

        self.assertEqual(resolved[0]["resolution"], "inline_source_data")
        self.assertEqual(resolved[0]["document"]["crew_id"], "crew-001")

    def test_iq_extracted_data_parses_retrieve_and_mcp_envelopes(self) -> None:
        encoded = json.dumps(
            [
                {
                    "ref_id": "0",
                    "vwi_code": "E-85",
                    "content": "Use the prescribed controls.",
                }
            ],
            indent=2,
        )
        retrieve_payload = {
            "response": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": encoded}],
                }
            ]
        }
        mcp_payload = {
            "result": {
                "content": [{"type": "text", "text": encoded}],
            }
        }

        self.assertEqual(
            rag.extract_iq_extracted_documents(retrieve_payload),
            rag.extract_iq_extracted_documents(mcp_payload),
        )
        self.assertEqual(
            rag.extract_iq_extracted_documents(retrieve_payload)[0]["vwi_code"],
            "E-85",
        )

    def test_iq_extracted_data_does_not_parse_synthesized_answer(self) -> None:
        payload = {
            "response": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "The procedure applies. [ref_id:0]",
                        }
                    ],
                }
            ]
        }

        self.assertEqual(rag.extract_iq_extracted_documents(payload), [])

    def test_iq_reference_resolution_can_use_extracted_response(self) -> None:
        extracted = json.dumps(
            [
                {
                    "ref_id": "7",
                    "id": "crew-001",
                    "crew_id": "crew-001",
                }
            ]
        )
        resolved = rag.fetch_iq_reference_documents(
            {
                "response": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": extracted}],
                    }
                ],
                "activity": [
                    {
                        "type": "searchIndex",
                        "id": 3,
                        "knowledgeSourceName": "crew-source",
                    }
                ],
                "references": [
                    {
                        "type": "searchIndex",
                        "id": "7",
                        "activitySource": "3",
                        "docKey": "crew-001",
                        "sourceData": None,
                    }
                ],
            },
            {},
        )

        self.assertEqual(resolved[0]["resolution"], "extracted_response")
        self.assertEqual(resolved[0]["document"]["crew_id"], "crew-001")

    def test_iq_reference_resolution_keeps_exact_extracted_evidence(self) -> None:
        extracted = json.dumps(
            [
                {
                    "ref_id": "7",
                    "content": "Only this extract was supplied to generation.",
                }
            ]
        )
        resolved = rag.fetch_iq_reference_documents(
            {
                "response": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": extracted}],
                    }
                ],
                "activity": [
                    {
                        "type": "searchIndex",
                        "id": 3,
                        "knowledgeSourceName": "crew-source",
                    }
                ],
                "references": [
                    {
                        "type": "searchIndex",
                        "id": "7",
                        "activitySource": 3,
                        "docKey": "crew-001",
                        "sourceData": {
                            "crew_id": "crew-001",
                            "content": "A broader source document.",
                            "shift_status_demo": "available",
                        },
                    }
                ],
            },
            {},
        )

        document = resolved[0]["document"]
        self.assertEqual(resolved[0]["resolution"], "extracted_response")
        self.assertEqual(
            document["content"],
            "Only this extract was supplied to generation.",
        )
        self.assertEqual(document["crew_id"], "crew-001")
        self.assertNotIn("shift_status_demo", document)

    def test_cost_estimate_is_explicit_and_does_not_invent_rates(self) -> None:
        usage = {
            "model_input_tokens": 1_000_000,
            "model_output_tokens": 500_000,
            "agentic_retrieval_tokens": 2_000_000,
            "semantic_requests": 1_000,
        }
        missing = rag.estimate_cost_usd(
            usage,
            {
                "model_input_per_1m": None,
                "model_output_per_1m": None,
                "semantic_per_1k": None,
                "agentic_per_1m": None,
            },
        )
        complete = rag.estimate_cost_usd(
            usage,
            {
                "model_input_per_1m": 1.0,
                "model_output_per_1m": 4.0,
                "semantic_per_1k": 2.0,
                "agentic_per_1m": 0.5,
            },
        )

        self.assertIsNone(missing["estimated_cost_usd"])
        self.assertFalse(missing["rates_complete"])
        self.assertEqual(complete["estimated_cost_usd"], 6.0)
        self.assertTrue(complete["rates_complete"])


if __name__ == "__main__":
    unittest.main()
