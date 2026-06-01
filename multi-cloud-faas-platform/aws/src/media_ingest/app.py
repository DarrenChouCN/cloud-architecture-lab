import base64
import binascii
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3


s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


@dataclass
class AppConfig:
    media_table: str
    assets_prefix: str
    azure_image_processing_endpoint: str
    azure_video_processing_endpoint: str
    presigned_url_expires_in: int
    azure_request_timeout: int
    media_bucket: Optional[str] = None
    azure_function_key: Optional[str] = None


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


# This Lambda is triggered by S3 uploads.
# It sends the original media file to Azure for analysis,
# stores the result in DynamoDB, and saves a thumbnail if available.
def lambda_handler(event, context):
    print("Received S3 event:")
    print(json.dumps(event))

    results = []

    # Process each uploaded S3 object from the event.
    for record in event.get("Records", []):
        uploaded = None

        try:
            # Parse the S3 object path and extract file metadata from it.
            uploaded = parse_s3_record(record)

            # Only process original image/video uploads.
            if not should_process(uploaded):
                print(f"Skipped object: {uploaded.object_key}")
                continue

            # Load the pending file record before starting ML processing.
            file_record = get_file_record(uploaded.file_id)

            if not file_record:
                raise ValueError(f"No DynamoDB record found for file_id={uploaded.file_id}")

            # Mark the file as processing before calling Azure.
            mark_file_as_processing(uploaded.file_id)

            # Give Azure temporary access to read the uploaded file.
            file_url = create_presigned_get_url(
                bucket=uploaded.bucket,
                object_key=uploaded.object_key,
            )

            payload = build_azure_payload(
                uploaded=uploaded,
                file_url=file_url,
            )

            # Send the file to Azure for image or video analysis.
            azure_result = send_to_azure_processing(
                payload=payload,
                file_type=uploaded.file_type,
            )

            # Save the generated thumbnail if Azure returned one.
            thumbnail_info = handle_thumbnail_if_present(
                uploaded=uploaded,
                azure_result=azure_result,
            )

            # Store the ML result and mark the file as completed.
            mark_file_as_completed(
                uploaded=uploaded,
                azure_result=azure_result,
                thumbnail_info=thumbnail_info,
            )

            results.append({
                "file_id": uploaded.file_id,
                "object_key": uploaded.object_key,
                "file_type": uploaded.file_type,
                "status": "COMPLETED",
                "tags": azure_result.get("tags", {}),
                "thumbnail_object_key": thumbnail_info.get("object_key") if thumbnail_info else None,
            })

        except Exception as error:
            print(f"Failed to process S3 record: {error}")

            if uploaded:
                mark_file_as_failed(
                    file_id=uploaded.file_id,
                    error_message=str(error),
                )

            results.append({
                "file_id": uploaded.file_id if uploaded else None,
                "object_key": uploaded.object_key if uploaded else None,
                "status": "FAILED",
                "error": str(error),
            })

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Media ingest event processed",
            "results": results,
        }, default=str),
    }


def load_config() -> AppConfig:
    media_table = os.environ.get("MEDIA_TABLE")

    if not media_table:
        raise RuntimeError("Missing required environment variable: MEDIA_TABLE")

    # Optional fallback keeps local tests compatible with the old single-endpoint version.
    legacy_endpoint = os.environ.get("AZURE_PROCESSING_ENDPOINT", "")

    return AppConfig(
        media_table=media_table,
        assets_prefix=os.environ.get("ASSETS_PREFIX", "assets/").strip("/"),
        azure_image_processing_endpoint=os.environ.get(
            "AZURE_IMAGE_PROCESSING_ENDPOINT",
            legacy_endpoint,
        ),
        azure_video_processing_endpoint=os.environ.get(
            "AZURE_VIDEO_PROCESSING_ENDPOINT",
            legacy_endpoint,
        ),
        presigned_url_expires_in=int(os.environ.get("PRESIGNED_URL_EXPIRES_IN", "3600")),
        azure_request_timeout=int(os.environ.get("AZURE_REQUEST_TIMEOUT", "30")),
        media_bucket=os.environ.get("MEDIA_BUCKET"),
        azure_function_key=os.environ.get("AZURE_FUNCTION_KEY"),
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

    # Optional bucket guard.
    if config.media_bucket and uploaded.bucket != config.media_bucket:
        return False

    if uploaded.file_type not in {"image", "video"}:
        return False

    # Avoid re-processing generated files.
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


def mark_file_as_completed(uploaded: UploadedObject, azure_result: dict, thumbnail_info: Optional[dict]):
    table = get_table()
    now = datetime.now(timezone.utc).isoformat()
    safe_processing_result = sanitize_azure_result_for_storage(azure_result)

    update_parts = [
        "#status = :status",
        "file_type = :file_type",
        "original_object_key = :original_object_key",
        "processing_result = :processing_result",
        "tags = :tags",
        "processed_at = :processed_at",
        "updated_at = :updated_at",
    ]

    expression_values = {
        ":status": "COMPLETED",
        ":file_type": uploaded.file_type,
        ":original_object_key": uploaded.object_key,
        ":processing_result": safe_processing_result,
        ":tags": azure_result.get("tags", {}),
        ":processed_at": now,
        ":updated_at": now,
    }

    if azure_result.get("model_version") is not None:
        update_parts.append("model_version = :model_version")
        expression_values[":model_version"] = azure_result["model_version"]

    if azure_result.get("frames_processed") is not None:
        update_parts.append("frames_processed = :frames_processed")
        expression_values[":frames_processed"] = azure_result["frames_processed"]

    if azure_result.get("crops_count") is not None:
        update_parts.append("crops_count = :crops_count")
        expression_values[":crops_count"] = azure_result["crops_count"]

    if thumbnail_info:
        update_parts.append("thumbnail_object_key = :thumbnail_object_key")
        update_parts.append("thumbnail_content_type = :thumbnail_content_type")
        expression_values[":thumbnail_object_key"] = thumbnail_info["object_key"]
        expression_values[":thumbnail_content_type"] = thumbnail_info["content_type"]

    table.update_item(
        Key={
            "pk": f"FILE#{uploaded.file_id}",
            "sk": "METADATA",
        },
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues=expression_values,
    )


def mark_file_as_failed(file_id: str, error_message: str):
    table = get_table()
    now = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={
            "pk": f"FILE#{file_id}",
            "sk": "METADATA",
        },
        UpdateExpression="""
            SET #status = :status,
                error_message = :error_message,
                failed_at = :failed_at,
                updated_at = :updated_at
        """,
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":status": "FAILED",
            ":error_message": error_message,
            ":failed_at": now,
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


def build_azure_payload(uploaded: UploadedObject, file_url: str) -> dict:
    return {
        "file_id": uploaded.file_id,
        "file_type": uploaded.file_type,
        "file_url": file_url,
        "bucket": uploaded.bucket,
        "object_key": uploaded.object_key,
        "filename": uploaded.filename,
    }


def send_to_azure_processing(payload: dict, file_type: str) -> dict:
    config = get_config()
    endpoint = get_azure_endpoint_for_file_type(file_type)

    request_body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
    }

    # Use this only if the function key is not already in the endpoint URL.
    if config.azure_function_key:
        headers["x-functions-key"] = config.azure_function_key

    request = urllib.request.Request(
        endpoint,
        data=request_body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.azure_request_timeout) as response:
            response_body = response.read().decode("utf-8")
            azure_result = parse_azure_response_body(response_body)

            if azure_result.get("status") == "error":
                raise RuntimeError(f"Azure processing returned error: {azure_result}")

            return azure_result

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8")
        raise RuntimeError(
            f"Azure processing failed with HTTP {error.code}: {error_body}"
        ) from error


def get_azure_endpoint_for_file_type(file_type: str) -> str:
    config = get_config()

    endpoint_by_type = {
        "image": config.azure_image_processing_endpoint,
        "video": config.azure_video_processing_endpoint,
    }

    endpoint = endpoint_by_type.get(file_type)

    if not endpoint:
        raise RuntimeError(f"Missing Azure processing endpoint for file_type={file_type}")

    return endpoint


def handle_thumbnail_if_present(uploaded: UploadedObject, azure_result: dict) -> Optional[dict]:
    if uploaded.file_type != "image":
        return None

    thumbnail = azure_result.get("thumbnail") or {}
    data_base64 = thumbnail.get("data_base64")

    if not data_base64:
        print("Azure image response did not include thumbnail.data_base64.")
        return None

    content_type = thumbnail.get("content_type") or "image/jpeg"
    thumbnail_bytes = decode_base64_payload(data_base64)
    thumbnail_key = build_thumbnail_object_key(uploaded, content_type)

    s3.put_object(
        Bucket=uploaded.bucket,
        Key=thumbnail_key,
        Body=thumbnail_bytes,
        ContentType=content_type,
    )

    return {
        "object_key": thumbnail_key,
        "content_type": content_type,
        "size_bytes": len(thumbnail_bytes),
    }


def build_thumbnail_object_key(uploaded: UploadedObject, content_type: str) -> str:
    config = get_config()
    extension = get_thumbnail_extension(content_type)

    return (
        f"{config.assets_prefix}/"
        f"{uploaded.user_id}/"
        f"{uploaded.file_type}/"
        f"{uploaded.file_id}/"
        f"thumbnail{extension}"
    )


def get_thumbnail_extension(content_type: str) -> str:
    extension_by_content_type = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    return extension_by_content_type.get(content_type.lower(), ".jpg")


def decode_base64_payload(data_base64: str) -> bytes:
    # Accept both raw base64 and data URL style payloads.
    if "," in data_base64 and data_base64.strip().lower().startswith("data:"):
        data_base64 = data_base64.split(",", 1)[1]

    try:
        return base64.b64decode(data_base64, validate=True)
    except binascii.Error as error:
        raise RuntimeError("Invalid thumbnail.data_base64 returned by Azure") from error


def sanitize_azure_result_for_storage(azure_result: dict) -> dict:
    # Avoid storing large base64 blobs inside DynamoDB.
    safe_result = dict(azure_result)

    if isinstance(safe_result.get("thumbnail"), dict):
        safe_thumbnail = dict(safe_result["thumbnail"])
        safe_thumbnail.pop("data_base64", None)
        safe_result["thumbnail"] = safe_thumbnail

    return safe_result


def parse_azure_response_body(response_body: str) -> dict:
    if not response_body:
        return {}

    try:
        return json.loads(response_body, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Azure returned non-JSON response: {response_body}") from error
