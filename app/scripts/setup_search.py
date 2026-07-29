"""
setup_search.py
Orchestrates the creation and population of the Azure AI Search index, plus
the upload of the structured lookup tables (crew, raamopdrachten, incidents)
to Blob Storage.

The core application indexes only the BEI-BLS rulebook corpus (logical base
name `idx_bls_corpus`). Crew and raamopdrachten remain deterministic local
tables at runtime. The optional Foundry IQ lab creates separate semantic copies
of those tables so participants can compare managed multi-source retrieval
without changing the reference application's safety gates.

Usage:
  python app/scripts/setup_search.py --all
  python app/scripts/setup_search.py --documents
  python app/scripts/setup_search.py --blob
  python app/scripts/setup_search.py --foundry-iq
"""
from __future__ import annotations

import argparse
import sys

import index_crew
import index_documents
import index_raamopdrachten
import setup_foundry_iq
import upload_crew_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up the Azure AI Search index for DRAAD.")
    parser.add_argument("--all", action="store_true", help="Index the BLS corpus AND upload blob data.")
    parser.add_argument("--documents", action="store_true", help="Index VWI PDF documents (idx_bls_corpus).")
    parser.add_argument("--blob", action="store_true", help="Upload crew/raamopdrachten/incidents JSON to Blob Storage.")
    parser.add_argument(
        "--foundry-iq",
        action="store_true",
        help=(
            "Create structured Search indexes plus the optional multi-source "
            "Foundry IQ knowledge base and MCP connection."
        ),
    )
    args = parser.parse_args()

    if not any([args.all, args.documents, args.blob, args.foundry_iq]):
        parser.print_help()
        sys.exit(1)

    if args.all or args.documents:
        print("\n=== Indexing VWI documents (idx_bls_corpus) ===")
        index_documents.main()

    if args.all or args.blob:
        print("\n=== Uploading lookup data to Blob Storage (crew-data) ===")
        upload_crew_data.run()

    if args.foundry_iq:
        print("\n=== Indexing authorization scopes for Foundry IQ ===")
        index_raamopdrachten.main()
        print("\n=== Indexing crew data for Foundry IQ ===")
        index_crew.main()
        print("\n=== Provisioning Foundry IQ knowledge resources ===")
        setup_foundry_iq.main([])

    print("\n✅ Search setup complete.")


if __name__ == "__main__":
    main()
