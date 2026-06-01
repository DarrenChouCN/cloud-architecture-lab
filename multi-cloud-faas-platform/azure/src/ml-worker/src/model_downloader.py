from pathlib import Path
import os

from azure.storage.blob import BlobServiceClient


MODEL_DIR = Path(os.getenv("MODEL_DIR", "./models"))
MODEL_FILES = ["mdv5a.pt", "model.pt"]


def get_blob_service_client() -> BlobServiceClient:
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)

    account_name = os.getenv("MODEL_STORAGE_ACCOUNT")
    account_key = os.getenv("MODEL_STORAGE_KEY")

    if not account_name or not account_key:
        raise RuntimeError(
            "Missing Azure Storage configuration. "
            "Set AZURE_STORAGE_CONNECTION_STRING or MODEL_STORAGE_ACCOUNT + MODEL_STORAGE_KEY."
        )

    account_url = f"https://{account_name}.blob.core.windows.net"
    return BlobServiceClient(account_url=account_url, credential=account_key)


def download_model_if_missing(file_name: str) -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    local_path = MODEL_DIR / file_name

    if local_path.exists() and local_path.stat().st_size > 0:
        print(f"Model already exists locally: {local_path}")
        return local_path

    container_name = os.getenv("MODEL_CONTAINER", "models")

    print(f"Downloading model from Azure Blob: {file_name}")

    blob_service_client = get_blob_service_client()
    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=file_name
    )

    with open(local_path, "wb") as f:
        stream = blob_client.download_blob()
        f.write(stream.readall())

    print(f"Downloaded model to: {local_path}")

    return local_path


def ensure_models_downloaded() -> None:
    for file_name in MODEL_FILES:
        download_model_if_missing(file_name)