"""
upload_crew_data.py
Uploads synth crew DB JSON, raamopdrachten JSON, and incidents JSON to Azure Blob Storage.

Usage (once synth data arrives from colleague):
  python scripts/upload_crew_data.py --crew data/crew.json --ro data/raamopdrachten.json --incidents data/incidents.json

Expects:
  data/crew.json           — list of crew records
  data/raamopdrachten.json — list of raamopdracht records
  data/incidents.json      — list of incident records
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")


def upload(account_url: str, container: str, local_path: Path, blob_name: str) -> None:
    credential = DefaultAzureCredential()
    client = BlobServiceClient(account_url=account_url, credential=credential)
    container_client = client.get_container_client(container)

    # Create container if it doesn't exist
    try:
        container_client.create_container()
        print(f"Created container '{container}'.")
    except Exception as exc:
        if "ContainerAlreadyExists" not in str(exc):
            print(f"WARNING: could not create container '{container}': {exc}")

    with open(local_path, "rb") as f:
        container_client.upload_blob(name=blob_name, data=f, overwrite=True)
    print(f"Uploaded '{local_path}' → '{container}/{blob_name}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload synth crew data to Blob Storage")
    parser.add_argument("--crew", default="data/crew.json", help="Path to crew.json")
    parser.add_argument("--ro", default="data/raamopdrachten.json", help="Path to raamopdrachten.json")
    parser.add_argument("--incidents", default="data/incidents.json", help="Path to incidents.json")
    args = parser.parse_args()

    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if not account_url:
        print("ERROR: AZURE_STORAGE_ACCOUNT_URL is not set.")
        sys.exit(1)

    container = os.getenv("AZURE_STORAGE_CREW_CONTAINER", "crew-data")

    crew_path = Path(args.crew)
    ro_path = Path(args.ro)
    incidents_path = Path(args.incidents)

    for p in (crew_path, ro_path, incidents_path):
        if not p.exists():
            print(f"WARNING: {p} not found — skipping. (Synth data not yet available?)")

    if crew_path.exists():
        upload(account_url, container, crew_path, "crew.json")
    if ro_path.exists():
        upload(account_url, container, ro_path, "raamopdrachten.json")
    if incidents_path.exists():
        upload(account_url, container, incidents_path, "incidents.json")


if __name__ == "__main__":
    main()
