"""
setup_search.py
Orchestrates the creation and population of the Azure AI Search index, plus
the upload of the structured lookup tables (crew, raamopdrachten, incidents)
to Blob Storage.

Only the BEI-BLS rulebook corpus is indexed (idx_bls_corpus). Crew and
raamopdrachten are small structured tables served from Blob Storage and
queried deterministically in Python — they are deliberately NOT indexed
(see docs/CONTEXT.md §2 and FAILURE_MODES.md #6/#7).

Usage:
  python scripts/setup_search.py --all         # index BLS corpus + upload blob data
  python scripts/setup_search.py --documents   # index BLS corpus only
  python scripts/setup_search.py --blob         # upload blob data only
"""
from __future__ import annotations

import argparse
import sys

import index_documents
import upload_crew_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up the Azure AI Search index for DRAAD.")
    parser.add_argument("--all", action="store_true", help="Index the BLS corpus AND upload blob data.")
    parser.add_argument("--documents", action="store_true", help="Index VWI PDF documents (idx_bls_corpus).")
    parser.add_argument("--blob", action="store_true", help="Upload crew/raamopdrachten/incidents JSON to Blob Storage.")
    args = parser.parse_args()

    if not any([args.all, args.documents, args.blob]):
        parser.print_help()
        sys.exit(1)

    if args.all or args.documents:
        print("\n=== Indexing VWI documents (idx_bls_corpus) ===")
        index_documents.main()

    if args.all or args.blob:
        print("\n=== Uploading lookup data to Blob Storage (crew-data) ===")
        upload_crew_data.run()

    print("\n✅ Search setup complete.")


if __name__ == "__main__":
    main()
