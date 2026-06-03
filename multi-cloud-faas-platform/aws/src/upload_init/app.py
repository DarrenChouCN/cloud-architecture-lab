import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError


s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
MEDIA_TABLE = os.environ["MEDIA_TABLE"]
ASSETS_PREFIX = os.environ.get("ASSETS_PREFIX", "uploads").strip("/")

table = dynamodb.Table(MEDIA_TABLE)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "video/mp4",
}


@dataclass
class UploadRequest:
    filename: str
    content_type: str
    checksum: str
    size: int

    @staticmethod
    def from_body(body: dict):
        return UploadRequest(
            filename=body["filename"],
            content_type=body["content_type"],
            checksum=body["checksum"],
            size=int(body["size"]),
        )

    def file_type(self):
        if self.content_type.startswith("image/"):
            return "image"
        if self.content_type.startswith("video/"):
            return "video"
        raise ValueError("Unsupported file type")

    def extension(self):
        return self.filename.split(".")[-1].lower()

# This Lambda initializes a file upload.
# It validates the request, checks duplicate files by checksum,
# saves a pending metadata record, and returns a pre-signed S3 upload URL.

def lambda_handler(event, context):
    try:
        # Extract the authenticated user from the API Gateway authorizer.
        user_id = get_user_id(event)

        # Parse and validate the upload request before creating any AWS resources.
        body = json.loads(event["body"])
        upload = UploadRequest.from_body(body)

        validate_request(upload)

        # Check whether the same file has already been uploaded by checksum.
        existing_file = find_existing_file(upload.checksum)
        if existing_file:
            return json_response(200, {
                "duplicated": True,
                "message": "File already exists",
                "file_id": existing_file["file_id"],
                "object_key": existing_file["object_key"],
                "status": existing_file.get("status"),
                "tags": existing_file.get("tags", {}),
                "thumbnail_url": existing_file.get("thumbnail_url"),
            })

        # Generate a unique file ID and build the final S3 object path.
        file_id = str(uuid.uuid4())
        object_key = build_object_key(user_id, file_id, upload)

        # Save a pending metadata record before the client uploads the file to S3.
        save_pending_record(
            user_id=user_id,
            file_id=file_id,
            object_key=object_key,
            upload=upload,
        )

        # Return a pre-signed URL so the client can upload directly to S3.
        upload_url = create_presigned_upload_url(
            object_key=object_key,
            content_type=upload.content_type,
        )

        return json_response(201, {
            "duplicated": False,
            "file_id": file_id,
            "object_key": object_key,
            "upload_url": upload_url,
            "expires_in": 900,
        })

    except KeyError as error:
        return json_response(400, {
            "message": f"Missing required field: {str(error)}"
        })

    except ValueError as error:
        return json_response(400, {
            "message": str(error)
        })

    except ClientError as error:
        print(error)
        return json_response(500, {
            "message": "AWS service error"
        })

    except Exception as error:
        print(error)
        return json_response(500, {
            "message": "Internal server error"
        })


def get_user_id(event):
    authorizer = event.get("requestContext", {}).get("authorizer", {})

    claims = authorizer.get("claims")
    if not claims:
        claims = authorizer.get("jwt", {}).get("claims", {})

    user_id = claims.get("sub")
    if not user_id:
        raise ValueError("User is not authenticated")

    return user_id


def validate_request(upload: UploadRequest):
    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError("Unsupported content type")

    if upload.size <= 0:
        raise ValueError("Invalid file size")

    if not upload.checksum:
        raise ValueError("checksum is required")

    if "." not in upload.filename:
        raise ValueError("filename must include extension")


def find_existing_file(checksum: str):
    # Use checksum as a lookup key to detect duplicate uploads.
    result = table.get_item(
        Key={
            "pk": f"CHECKSUM#{checksum}",
            "sk": "METADATA",
        }
    )

    checksum_record = result.get("Item")
    if not checksum_record:
        return None

    file_id = checksum_record["file_id"]

    # If a checksum record exists, fetch the real file metadata by file ID.
    file_result = table.get_item(
        Key={
            "pk": f"FILE#{file_id}",
            "sk": "METADATA",
        }
    )

    return file_result.get("Item")


def build_object_key(user_id: str, file_id: str, upload: UploadRequest):
    return (
        f"{ASSETS_PREFIX}/{user_id}/"
        f"{upload.file_type()}/"
        f"{file_id}/"
        f"original.{upload.extension()}"
    )


def save_pending_record(
    user_id: str,
    file_id: str,
    object_key: str,
    upload: UploadRequest,
):
    now = datetime.now(timezone.utc).isoformat()

    # Main file metadata item.
    file_record = {
        "pk": f"FILE#{file_id}",
        "sk": "METADATA",
        "file_id": file_id,
        "user_id": user_id,
        "original_filename": upload.filename,
        "content_type": upload.content_type,
        "file_type": upload.file_type(),
        "checksum": upload.checksum,
        "size": Decimal(upload.size),
        "bucket": MEDIA_BUCKET,
        "object_key": object_key,
        "status": "PENDING_UPLOAD",
        "created_at": now,
        "updated_at": now,
    }

    # Secondary lookup item used for duplicate detection.
    checksum_record = {
        "pk": f"CHECKSUM#{upload.checksum}",
        "sk": "METADATA",
        "file_id": file_id,
        "object_key": object_key,
        "created_at": now,
    }

    table.put_item(Item=file_record)
    table.put_item(Item=checksum_record)


def create_presigned_upload_url(object_key: str, content_type: str):
    # The URL is valid for 15 minutes and only allows uploading this object.
    return s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": MEDIA_BUCKET,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=900,
        HttpMethod="PUT",
    )


def json_response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }