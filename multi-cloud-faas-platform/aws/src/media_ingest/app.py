import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import boto3


s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


@dataclass
class AppConfig:
    media_table: str
    assets_prefix: str
    azure_processing_endpoint: str
    presigned_url_expires_in: int
    media_bucket: Optional[str] = None


@dataclass
class UploadedObject:
    bucket: str
    object_key: str
    user_id: str
    file_type: str
    file_id: str
    filename: str


_config = None
_table = None


def lambda_handler(event, context):
    print("Received S3 event:")
    print(json.dumps(event))

    results = []

    for record in event.get("Records", []):
        try:
            uploaded = parse_s3_record(record)

            if not should_process(uploaded):
                print(f"Skipped object: {uploaded.object_key}")
                continue

            file_record = get_file_record(uploaded.file_id)

            if not file_record:
                raise ValueError(f"No DynamoDB record found for file_id={uploaded.file_id}")

            mark_file_as_processing(uploaded.file_id)

            file_url = create_presigned_get_url(
                bucket=uploaded.bucket,
                object_key=uploaded.object_key,
            )

            payload = {
                "file_id": uploaded.file_id,
                "file_type": uploaded.file_type,
                "bucket": uploaded.bucket,
                "object_key": uploaded.object_key,
                "filename": uploaded.filename,
                "presigned_get_url": file_url,

                # TODO:
                # Replace this with the real AWS callback URL later.
                # Azure Function will call it after thumbnail/tagging processing is done.
                "callback_url": "",
            }

            azure_result = send_to_azure_processing(payload)

            results.append({
                "file_id": uploaded.file_id,
                "object_key": uploaded.object_key,
                "status": "PROCESSING",
                "azure_dispatch": azure_result,
            })

        except Exception as error:
            print(f"Failed to process S3 record: {error}")

            results.append({
                "status": "FAILED",
                "error": str(error),
            })

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Media ingest event processed",
            "results": results,
        }),
    }


def load_config() -> AppConfig:
    media_table = os.environ.get("MEDIA_TABLE")

    if not media_table:
        raise RuntimeError("Missing required environment variable: MEDIA_TABLE")

    return AppConfig(
        media_table=media_table,
        assets_prefix=os.environ.get("ASSETS_PREFIX", "assets/").strip("/"),
        azure_processing_endpoint=os.environ.get("AZURE_PROCESSING_ENDPOINT", ""),
        presigned_url_expires_in=int(os.environ.get("PRESIGNED_URL_EXPIRES_IN", "3600")),
        media_bucket=os.environ.get("MEDIA_BUCKET"),
    )


def get_config() -> AppConfig:
    global _config

    if _config is None:
        _config = load_config()

    return _config


def get_table():
    global _table

    if _table is None:
        config = get_config()
        _table = dynamodb.Table(config.media_table)

    return _table


def parse_s3_record(record) -> UploadedObject:
    config = get_config()

    bucket = record["s3"]["bucket"]["name"]

    raw_key = record["s3"]["object"]["key"]
    object_key = urllib.parse.unquote_plus(raw_key)

    prefix = config.assets_prefix.strip("/") + "/"

    if not object_key.startswith(prefix):
        raise ValueError(f"Object key does not match prefix: {object_key}")

    relative_key = object_key[len(prefix):]
    parts = relative_key.split("/")

    if len(parts) < 4:
        raise ValueError(f"Unexpected object key format: {object_key}")

    return UploadedObject(
        bucket=bucket,
        object_key=object_key,
        user_id=parts[0],
        file_type=parts[1],
        file_id=parts[2],
        filename=parts[-1],
    )


def should_process(uploaded: UploadedObject) -> bool:
    config = get_config()

    # Optional safety check.
    # In this project, the S3 event itself already tells us the source bucket.
    if config.media_bucket and uploaded.bucket != config.media_bucket:
        return False

    if uploaded.file_type not in {"image", "video"}:
        return False

    # Only process original uploaded files.
    # This prevents future thumbnails or processed files from triggering this pipeline again.
    if not uploaded.filename.startswith("original."):
        return False

    return True


def get_file_record(file_id: str) -> Optional[dict]:
    table = get_table()

    result = table.get_item(
        Key={
            "pk": f"FILE#{file_id}",
            "sk": "METADATA",
        }
    )

    return result.get("Item")


def mark_file_as_processing(file_id: str):
    table = get_table()
    now = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={
            "pk": f"FILE#{file_id}",
            "sk": "METADATA",
        },
        UpdateExpression="""
            SET #status = :status,
                updated_at = :updated_at
        """,
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":status": "PROCESSING",
            ":updated_at": now,
        },
    )


def create_presigned_get_url(bucket: str, object_key: str) -> str:
    config = get_config()

    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": bucket,
            "Key": object_key,
        },
        ExpiresIn=config.presigned_url_expires_in,
        HttpMethod="GET",
    )


def send_to_azure_processing(payload: dict) -> dict:
    config = get_config()

    if not config.azure_processing_endpoint:
        print("Azure processing endpoint is not configured yet.")
        print("TODO: Set AZURE_PROCESSING_ENDPOINT after Azure Function is deployed.")
        print("Payload that would be sent to Azure:")
        print(json.dumps(payload))

        return {
            "called": False,
            "reason": "AZURE_PROCESSING_ENDPOINT is empty",
        }

    request_body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        config.azure_processing_endpoint,
        data=request_body,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        response_body = response.read().decode("utf-8")

        return {
            "called": True,
            "status_code": response.status,
            "response": response_body,
        }