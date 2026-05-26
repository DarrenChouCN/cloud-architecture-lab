from datetime import datetime, timezone
import urllib.parse

from boto3.dynamodb.conditions import Attr

from app import ValidationError


def bulk_update_tags(body, request_context, config, table) -> dict:
    urls = parse_urls(body)
    tags_to_modify = parse_tags(body)
    operation = parse_operation(body)

    object_keys = {
        extract_s3_key(url, config.media_bucket)
        for url in urls
    }

    items = find_items_by_object_keys(table, object_keys)

    results = []
    matched_keys = set()

    for item in items:
        item_keys = get_item_object_keys(item)
        matched_keys.update(item_keys.intersection(object_keys))

        current_tags = normalize_existing_tags(item.get("tags"))
        updated_tags = apply_tag_operation(
            current_tags=current_tags,
            tags_to_modify=tags_to_modify,
            operation=operation,
        )

        update_item_tags(
            table=table,
            item=item,
            tags=updated_tags,
        )

        results.append({
            "file_id": get_file_id(item),
            "operation": operation,
            "tags": updated_tags,
            "matched_object_keys": sorted(item_keys.intersection(object_keys)),
        })

    not_found = sorted(object_keys - matched_keys)

    return {
        "message": "Bulk tag update completed",
        "operation": operation,
        "updated_count": len(results),
        "not_found_count": len(not_found),
        "updated_files": results,
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


def parse_tags(body) -> list:
    raw_tags = body.get("tags")

    if isinstance(raw_tags, dict):
        raw_tags = list(raw_tags.keys())

    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]

    if not isinstance(raw_tags, list) or not raw_tags:
        raise ValidationError("tags must be a non-empty list")

    tags = [
        normalize_tag_name(tag)
        for tag in raw_tags
        if normalize_tag_name(tag)
    ]

    if not tags:
        raise ValidationError("At least one valid tag is required")

    return tags


def parse_operation(body) -> str:
    raw_operation = body.get("operation")

    if raw_operation in [1, "1", "add", "ADD", "Add"]:
        return "add"

    if raw_operation in [0, "0", "remove", "REMOVE", "Remove", "delete", "DELETE"]:
        return "remove"

    raise ValidationError("operation must be 1/add or 0/remove")


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


def apply_tag_operation(current_tags: dict, tags_to_modify: list, operation: str) -> dict:
    updated_tags = dict(current_tags)

    for tag in tags_to_modify:
        if operation == "add":
            updated_tags.setdefault(tag, 1)

        if operation == "remove":
            updated_tags.pop(tag, None)

    return updated_tags


def update_item_tags(table, item: dict, tags: dict):
    now = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={
            "pk": item["pk"],
            "sk": item["sk"],
        },
        UpdateExpression="""
            SET tags = :tags,
                updated_at = :updated_at
        """,
        ExpressionAttributeValues={
            ":tags": tags,
            ":updated_at": now,
        },
    )


def normalize_existing_tags(tags) -> dict:
    if isinstance(tags, dict):
        normalized_tags = {}

        for tag, count in tags.items():
            tag_name = normalize_tag_name(tag)

            if not tag_name:
                continue

            try:
                normalized_tags[tag_name] = int(count)
            except (TypeError, ValueError):
                normalized_tags[tag_name] = 1

        return normalized_tags

    if isinstance(tags, list):
        return {
            normalize_tag_name(tag): 1
            for tag in tags
            if normalize_tag_name(tag)
        }

    return {}


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


def normalize_tag_name(value) -> str:
    return str(value).strip().lower()


def get_file_id(item: dict) -> str:
    if item.get("file_id"):
        return item["file_id"]

    pk = item.get("pk", "")

    if pk.startswith("FILE#"):
        return pk.split("#", 1)[1]

    return pk