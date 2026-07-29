"""
upload_crew_data.py
Uploads the synthetic crew, raamopdracht, and incident fixtures to Azure Blob
Storage.

Usage:
  python scripts/upload_crew_data.py --crew data/crew.json --ro data/raamopdrachten.json --incidents data/incidents.json

Expects:
  data/crew.json           — list of crew records
  data/raamopdrachten.json — list of raamopdracht records
  data/incidents.json      — list of incident records
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

from shared import scoped_name

load_dotenv(Path(__file__).parent.parent.parent / ".env")
APP_ROOT = Path(__file__).resolve().parent.parent


def _scoped_container_name() -> str:
    return scoped_name("crew-data", "AZURE_STORAGE_CREW_CONTAINER")


def upload(account_url: str, container: str, local_path: Path, blob_name: str) -> None:
    credential = DefaultAzureCredential()
    client = BlobServiceClient(account_url=account_url, credential=credential)
    container_client = client.get_container_client(container)

    # Create container if it doesn't exist
    try:
        container_client.create_container()
        print(f"Created container '{container}'.")
    except ResourceExistsError:
        pass

    with open(local_path, "rb") as f:
        container_client.upload_blob(name=blob_name, data=f, overwrite=True)
    print(f"Uploaded '{local_path}' → '{container}/{blob_name}'.")


def run(
    crew: str | Path = APP_ROOT / "data" / "crew.json",
    ro: str | Path = APP_ROOT / "data" / "raamopdrachten.json",
    incidents: str | Path = APP_ROOT / "data" / "incidents.json",
) -> None:
    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if not account_url:
        print("ERROR: AZURE_STORAGE_ACCOUNT_URL is not set.")
        sys.exit(1)

    container = _scoped_container_name()

    crew_path = Path(crew)
    ro_path = Path(ro)
    incidents_path = Path(incidents)

    for p in (crew_path, ro_path, incidents_path):
        if not p.exists():
            print(f"WARNING: {p} not found — skipping. (Synth data not yet available?)")

    if crew_path.exists():
        upload(account_url, container, crew_path, "crew.json")
    if ro_path.exists():
        upload(account_url, container, ro_path, "raamopdrachten.json")
    if incidents_path.exists():
        upload(account_url, container, incidents_path, "incidents.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload synth crew data to Blob Storage")
    parser.add_argument("--crew", default=APP_ROOT / "data" / "crew.json", help="Path to crew.json")
    parser.add_argument("--ro", default=APP_ROOT / "data" / "raamopdrachten.json", help="Path to raamopdrachten.json")
    parser.add_argument("--incidents", default=APP_ROOT / "data" / "incidents.json", help="Path to incidents.json")
    args = parser.parse_args()

    run(crew=args.crew, ro=args.ro, incidents=args.incidents)


if __name__ == "__main__":
    main()
