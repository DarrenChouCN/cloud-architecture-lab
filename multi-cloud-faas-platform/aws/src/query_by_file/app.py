import base64
import json
import os
import urllib.error
import urllib.request
import uuid
from decimal import Decimal

import boto3


s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


# This Lambda supports query-by-file search.
# It uploads the query file temporarily, asks Azure to detect tags,
# searches existing completed media by those tags, and cleans up the temp file.
def lambda_handler(event, context):
    temp_key = None

    try:
        # Read the authenticated user and parse the uploaded query file.
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        user_id = claims.get("sub", "anonymous")

        body = parse_body(event)

        filename = body.get("filename", "query-file")
        content_type = body.get("content_type", "application/octet-stream")
        file_type = body.get("file_type") or infer_file_type(content_type)
        # Decode the uploaded file and store it temporarily in S3.
        file_bytes = decode_base64_file(body.get("data_base64"))

        query_id = str(uuid.uuid4())
        temp_key = build_temp_key(user_id, query_id, filename)

        upload_temp_file(temp_key, file_bytes, content_type)

        # Send a temporary file URL to Azure for analysis.
        file_url = create_presigned_url(temp_key)

        azure_result = analyze_query_file(
            query_id=query_id,
            file_type=file_type,
            file_url=file_url,
        )

        # Use detected tags to find matching completed files.
        detected_tags = normalize_tags(azure_result.get("tags", {}))
        matched_files = find_matching_files(detected_tags)

        return response(200, {
            "query_id": query_id,
            "status": "success",
            "file_type": file_type,
            "detected_tags": detected_tags,
            "matched_count": len(matched_files),
            "matched_files": matched_files,
            "azure_result": azure_result,
        })

    except Exception as error:
        print(f"Query by file failed: {error}")

        return response(500, {
            "message": str(error),
            "error_code": "query_by_file_failed",
        })

    # Always delete the temporary query file after processing.
    finally:
        if temp_key:
            delete_temp_file(temp_key)


def parse_body(event):
    raw_body = event.get("body") or "{}"

    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    return json.loads(raw_body)


def decode_base64_file(data_base64):
    if not data_base64:
        raise ValueError("Missing data_base64")

    # Support data URL format: data:image/jpeg;base64,...
    if "," in data_base64 and data_base64.strip().lower().startswith("data:"):
        data_base64 = data_base64.split(",", 1)[1]

    return base64.b64decode(data_base64)


def infer_file_type(content_type):
    if content_type.startswith("image/"):
        return "image"

    if content_type.startswith("video/"):
        return "video"

    raise ValueError("file_type must be image or video")


def build_temp_key(user_id, query_id, filename):
    prefix = os.environ.get("QUERY_FILE_TEMP_PREFIX", "query-temp/").strip("/")
    safe_filename = filename.replace("/", "_")

    return f"{prefix}/{user_id}/{query_id}/{safe_filename}"


def upload_temp_file(object_key, file_bytes, content_type):
    s3.put_object(
        Bucket=os.environ["MEDIA_BUCKET"],
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
    )


def create_presigned_url(object_key):
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": os.environ["MEDIA_BUCKET"],
            "Key": object_key,
        },
        ExpiresIn=int(os.environ.get("PRESIGNED_URL_EXPIRES_IN", "3600")),
        HttpMethod="GET",
    )


def analyze_query_file(query_id, file_type, file_url):
    payload = {
        "query_id": query_id,
        "file_type": file_type,
        "file_url": file_url,
        "model_version": os.environ.get("MODEL_VERSION", "current"),
    }

    request = urllib.request.Request(
        os.environ["QUERY_FILE_ANALYSIS_ENDPOINT"],
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=int(os.environ.get("QUERY_FILE_REQUEST_TIMEOUT", "25")),
        ) as response_obj:
            response_body = response_obj.read().decode("utf-8")
            return json.loads(response_body, parse_float=Decimal)

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8")
        raise RuntimeError(f"Azure query analysis failed: {error.code} {error_body}") from error


def find_matching_files(detected_tags):
    if not detected_tags:
        return []

    table = dynamodb.Table(os.environ["MEDIA_TABLE"])

    items = []
    scan_kwargs = {}

    while True:
        result = table.scan(**scan_kwargs)
        items.extend(result.get("Items", []))

        if "LastEvaluatedKey" not in result:
            break

        scan_kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]

    matched = []

    for item in items:
        if item.get("sk") != "METADATA":
            continue

        if item.get("status") != "COMPLETED":
            continue

        existing_tags = normalize_tags(item.get("tags", {}))

        if all(tag in existing_tags for tag in detected_tags.keys()):
            matched.append(build_file_response(item))

    return matched


def build_file_response(item):
    original_key = item.get("original_object_key")
    thumbnail_key = item.get("thumbnail_object_key")
    file_type = item.get("file_type")

    original_url = create_presigned_url(original_key) if original_key else None
    thumbnail_url = create_presigned_url(thumbnail_key) if thumbnail_key else None

    return {
        "file_id": get_file_id(item),
        "file_type": file_type,
        "tags": item.get("tags", {}),
        "url": thumbnail_url if file_type == "image" and thumbnail_url else original_url,
        "original_url": original_url,
        "thumbnail_url": thumbnail_url,
    }


def normalize_tags(tags):
    if isinstance(tags, dict):
        return {
            str(tag).strip().lower(): int(count)
            for tag, count in tags.items()
            if str(tag).strip()
        }

    if isinstance(tags, list):
        return {
            str(tag).strip().lower(): 1
            for tag in tags
            if str(tag).strip()
        }

    return {}


def get_file_id(item):
    pk = item.get("pk", "")

    if pk.startswith("FILE#"):
        return pk.split("#", 1)[1]

    return item.get("file_id", pk)


def delete_temp_file(object_key):
    try:
        s3.delete_object(
            Bucket=os.environ["MEDIA_BUCKET"],
            Key=object_key,
        )
    except Exception as error:
        print(f"Failed to delete temp query file: {error}")


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, default=str),
    }