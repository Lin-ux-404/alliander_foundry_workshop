"""
setup_search.py
Orchestrates the creation and population of all Azure AI Search indexes.

Usage:
  python scripts/setup_search.py --all
  python scripts/setup_search.py --documents
  python scripts/setup_search.py --crew
  python scripts/setup_search.py --raamopdrachten
"""
from __future__ import annotations

import argparse
import sys

import index_documents
import index_crew
import index_raamopdrachten


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Azure AI Search indexes for DRAAD.")
    parser.add_argument("--all", action="store_true", help="Create and populate all indexes.")
    parser.add_argument("--documents", action="store_true", help="Index VWI PDF documents.")
    parser.add_argument("--crew", action="store_true", help="Index crew records.")
    parser.add_argument("--raamopdrachten", action="store_true", help="Index raamopdrachten records.")
    args = parser.parse_args()

    if not any([args.all, args.documents, args.crew, args.raamopdrachten]):
        parser.print_help()
        sys.exit(1)

    if args.all or args.documents:
        print("\n=== Indexing VWI documents (idx_bls_corpus) ===")
        index_documents.main()

    if args.all or args.raamopdrachten:
        print("\n=== Indexing raamopdrachten (idx_raamopdrachten) ===")
        index_raamopdrachten.main()

    if args.all or args.crew:
        print("\n=== Indexing crew (idx_crew) ===")
        index_crew.main()

    print("\n✅ Search setup complete.")


if __name__ == "__main__":
    main()
