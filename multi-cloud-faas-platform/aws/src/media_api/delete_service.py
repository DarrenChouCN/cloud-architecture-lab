import urllib.parse

from boto3.dynamodb.conditions import Attr

from app import ValidationError

# This service deletes media files requested by URL.
# It converts URLs to S3 object keys, finds matching metadata records,
# deletes the related S3 objects, and then removes the DynamoDB records.

def delete_files(body, request_context, config, table, s3_client) -> dict:
    # Parse the requested file URLs from the request body.
    urls = parse_urls(body)

    # Convert each public file URL back to its S3 object key.
    object_keys = {
        extract_s3_key(url, config.media_bucket)
        for url in urls
    }

    # Find the DynamoDB metadata records that match these S3 object keys.
    items = find_items_by_object_keys(table, object_keys)

    deleted_files = []
    matched_keys = set()

    # Delete all S3 objects related to each matched file,
    # then remove its metadata record from DynamoDB.
    for item in items:
        item_keys = get_item_object_keys(item)
        matched_keys.update(item_keys.intersection(object_keys))

        deleted_object_keys = delete_s3_objects(
            object_keys=item_keys,
            config=config,
            s3_client=s3_client,
        )

        delete_metadata_record(
            table=table,
            item=item,
        )

        deleted_files.append({
            "file_id": get_file_id(item),
            "deleted_object_keys": deleted_object_keys,
        })

    # Report which requested files were deleted and which were not found.
    not_found = sorted(object_keys - matched_keys)

    return {
        "message": "Delete files completed",
        "deleted_count": len(deleted_files),
        "not_found_count": len(not_found),
        "deleted_files": deleted_files,
        "not_found_object_keys": not_found,
    }


def parse_urls(body) -> list:
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")

    raw_urls = (
        body.get("urls")
        or body.get("file_urls")
        or body.get("media_urls")
        or body.get("url")
    )

    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]

    if not isinstance(raw_urls, list) or not raw_urls:
        raise ValidationError("urls must be a non-empty list")

    return [
        str(url).strip()
        for url in raw_urls
        if str(url).strip()
    ]


def find_items_by_object_keys(table, object_keys: set) -> list:
    matched_items = []
    scan_kwargs = {
        "FilterExpression": Attr("sk").eq("METADATA"),
    }

    while True:
        response = table.scan(**scan_kwargs)

        for item in response.get("Items", []):
            if get_item_object_keys(item).intersection(object_keys):
                matched_items.append(item)

        last_key = response.get("LastEvaluatedKey")

        if not last_key:
            break

        scan_kwargs["ExclusiveStartKey"] = last_key

    return matched_items


def delete_s3_objects(object_keys: set, config, s3_client) -> list:
    deleted_keys = []

    for object_key in object_keys:
        s3_client.delete_object(
            Bucket=config.media_bucket,
            Key=object_key,
        )

        deleted_keys.append(object_key)

    return sorted(deleted_keys)


def delete_metadata_record(table, item: dict):
    table.delete_item(
        Key={
            "pk": item["pk"],
            "sk": item["sk"],
        }
    )


def get_item_object_keys(item: dict) -> set:
    keys = set()

    if item.get("original_object_key"):
        keys.add(item["original_object_key"])

    if item.get("thumbnail_object_key"):
        keys.add(item["thumbnail_object_key"])

    return keys


def extract_s3_key(value: str, bucket_name: str) -> str:
    if not value:
        raise ValidationError("URL is required")

    text = str(value).strip()

    if text.startswith("s3://"):
        parsed = urllib.parse.urlparse(text)
        return urllib.parse.unquote(parsed.path.lstrip("/"))

    if text.startswith("http://") or text.startswith("https://"):
        parsed = urllib.parse.urlparse(text)
        path = urllib.parse.unquote(parsed.path.lstrip("/"))

        if path.startswith(f"{bucket_name}/"):
            path = path[len(bucket_name) + 1:]

        return path

    return urllib.parse.unquote(text.lstrip("/"))


def get_file_id(item: dict) -> str:
    if item.get("file_id"):
        return item["file_id"]

    pk = item.get("pk", "")

    if pk.startswith("FILE#"):
        return pk.split("#", 1)[1]

    return pk