import urllib.parse
from typing import Any

from boto3.dynamodb.conditions import Attr

from app import NotFoundError, ValidationError


def find_files_by_tags(body, request_context, config, table, s3_client) -> dict:
    requested_tags = parse_requested_tags(body)

    items = scan_metadata_items(table)

    matched_items = [
        item for item in items
        if is_completed_file(item) and matches_all_tags(item, requested_tags)
    ]

    return {
        "query": {
            "tags": requested_tags,
        },
        "count": len(matched_items),
        "files": [
            build_file_response(item, config, s3_client)
            for item in matched_items
        ],
    }


def find_files_by_species(species, request_context, config, table, s3_client) -> dict:
    species_name = str(species).strip().lower()

    if not species_name:
        raise ValidationError("Species is required")

    items = scan_metadata_items(table)

    matched_items = [
        item for item in items
        if is_completed_file(item) and get_tag_count(item.get("tags"), species_name) >= 1
    ]

    return {
        "query": {
            "species": species_name,
        },
        "count": len(matched_items),
        "files": [
            build_file_response(item, config, s3_client)
            for item in matched_items
        ],
    }


def find_file_by_thumbnail_url(thumbnail_url, request_context, config, table, s3_client) -> dict:
    thumbnail_object_key = extract_s3_key(
        value=thumbnail_url,
        bucket_name=config.media_bucket,
    )

    items = scan_metadata_items(table)

    for item in items:
        if item.get("thumbnail_object_key") == thumbnail_object_key:
            return {
                "thumbnail_object_key": thumbnail_object_key,
                "file": build_file_response(item, config, s3_client),
            }

    raise NotFoundError(
        message="No file found for the provided thumbnail URL",
        details={
            "thumbnail_object_key": thumbnail_object_key,
        },
    )


def parse_requested_tags(body: Any) -> dict:
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")

    raw_tags = body.get("tags", body)

    if not raw_tags:
        raise ValidationError("At least one tag is required")

    if isinstance(raw_tags, list):
        return {
            normalize_tag_name(tag): 1
            for tag in raw_tags
            if str(tag).strip()
        }

    if isinstance(raw_tags, dict):
        parsed_tags = {}

        for tag, count in raw_tags.items():
            tag_name = normalize_tag_name(tag)

            if not tag_name:
                continue

            parsed_tags[tag_name] = parse_min_count(count)

        if not parsed_tags:
            raise ValidationError("At least one valid tag is required")

        return parsed_tags

    raise ValidationError("tags must be either an object or a list")


def parse_min_count(value) -> int:
    if value is None or value == "":
        return 1

    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Tag count must be a number")

    if count < 1:
        raise ValidationError("Tag count must be greater than zero")

    return count


def scan_metadata_items(table) -> list:
    items = []
    scan_kwargs = {
        "FilterExpression": Attr("sk").eq("METADATA"),
    }

    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))

        last_key = response.get("LastEvaluatedKey")

        if not last_key:
            break

        scan_kwargs["ExclusiveStartKey"] = last_key

    return items


def is_completed_file(item: dict) -> bool:
    return item.get("status") == "COMPLETED"


def matches_all_tags(item: dict, requested_tags: dict) -> bool:
    existing_tags = item.get("tags") or {}

    for tag_name, min_count in requested_tags.items():
        if get_tag_count(existing_tags, tag_name) < min_count:
            return False

    return True


def get_tag_count(tags, tag_name: str) -> int:
    normalized_name = normalize_tag_name(tag_name)

    if isinstance(tags, dict):
        normalized_tags = {
            normalize_tag_name(key): value
            for key, value in tags.items()
        }

        value = normalized_tags.get(normalized_name, 0)

        try:
            return int(value)
        except (TypeError, ValueError):
            return 1 if value else 0

    if isinstance(tags, list):
        normalized_tags = {
            normalize_tag_name(tag)
            for tag in tags
        }

        return 1 if normalized_name in normalized_tags else 0

    return 0


def build_file_response(item: dict, config, s3_client) -> dict:
    file_type = item.get("file_type")
    original_object_key = item.get("original_object_key")
    thumbnail_object_key = item.get("thumbnail_object_key")

    original_url = create_presigned_get_url(
        object_key=original_object_key,
        config=config,
        s3_client=s3_client,
    )

    thumbnail_url = create_presigned_get_url(
        object_key=thumbnail_object_key,
        config=config,
        s3_client=s3_client,
    )

    primary_url = original_url

    if file_type == "image" and thumbnail_url:
        primary_url = thumbnail_url

    return {
        "file_id": get_file_id(item),
        "file_type": file_type,
        "status": item.get("status"),
        "tags": item.get("tags", {}),
        "url": primary_url,
        "original_url": original_url,
        "thumbnail_url": thumbnail_url,
        "original_object_key": original_object_key,
        "thumbnail_object_key": thumbnail_object_key,
    }


def create_presigned_get_url(object_key: str, config, s3_client):
    if not object_key:
        return None

    return s3_client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": config.media_bucket,
            "Key": object_key,
        },
        ExpiresIn=config.presigned_url_expires_in,
        HttpMethod="GET",
    )


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