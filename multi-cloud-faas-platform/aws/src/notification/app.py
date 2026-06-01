import json
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeDeserializer


sns = boto3.client("sns")
deserializer = TypeDeserializer()


# This Lambda listens to DynamoDB Streams.
# When a completed media record gets new or changed tags,
# it publishes a notification event to SNS.
def lambda_handler(event, context):
    published = 0
    skipped = 0

    # Process DynamoDB Stream records and publish only meaningful tag updates.
    for record in event.get("Records", []):
        try:
            # Skip records that are not completed media metadata changes.
            if not should_publish(record):
                skipped += 1
                continue

            # Convert DynamoDB Stream format back to a normal Python dictionary.
            item = deserialize_image(record["dynamodb"]["NewImage"])
            # Publish a media tagged event to SNS.
            publish_media_tagged_event(item)
            published += 1

        except Exception as error:
            print(f"Failed to process stream record: {error}")
            skipped += 1

    return {
        "published": published,
        "skipped": skipped,
    }


def should_publish(record):
    if record.get("eventName") not in {"INSERT", "MODIFY"}:
        return False

    dynamodb = record.get("dynamodb", {})
    new_image = dynamodb.get("NewImage")

    if not new_image:
        return False

    new_item = deserialize_image(new_image)

    if new_item.get("sk") != "METADATA":
        return False

    if new_item.get("status") != "COMPLETED":
        return False

    new_tags = normalize_tags(new_item.get("tags", {}))

    if not new_tags:
        return False

    old_image = dynamodb.get("OldImage")

    if not old_image:
        return True

    old_item = deserialize_image(old_image)
    old_tags = normalize_tags(old_item.get("tags", {}))

    if old_item.get("status") != "COMPLETED":
        return True

    return old_tags != new_tags


def publish_media_tagged_event(item):
    tags = sorted(normalize_tags(item.get("tags", {})).keys())

    message = {
        "event_type": "MediaTagged",
        "file_id": get_file_id(item),
        "file_type": item.get("file_type"),
        "tags": normalize_tags(item.get("tags", {})),
        "original_object_key": item.get("original_object_key"),
        "thumbnail_object_key": item.get("thumbnail_object_key"),
    }

    sns.publish(
        TopicArn=get_env("SNS_TOPIC_ARN"),
        Subject="Aussie EcoLens media tagged",
        Message=json.dumps(message, cls=DecimalEncoder, indent=2),
        MessageAttributes={
            "event_type": {
                "DataType": "String",
                "StringValue": "MediaTagged",
            },
            "file_type": {
                "DataType": "String",
                "StringValue": item.get("file_type", "unknown"),
            },
            "tags": {
                "DataType": "String.Array",
                "StringValue": json.dumps(tags),
            },
        },
    )


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


def deserialize_image(image):
    return {
        key: deserializer.deserialize(value)
        for key, value in image.items()
    }


def get_file_id(item):
    pk = item.get("pk", "")

    if pk.startswith("FILE#"):
        return pk.split("#", 1)[1]

    return item.get("file_id", pk)


def get_env(name):
    value = __import__("os").environ.get(name)

    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

    return value


class DecimalEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, Decimal):
            if value % 1 == 0:
                return int(value)

            return float(value)

        return super().default(value)