import base64
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

import boto3


s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


@dataclass
class AppConfig:
    media_bucket: str
    media_table: str
    assets_prefix: str
    presigned_url_expires_in: int


@dataclass
class RequestContext:
    route_key: str
    method: str
    path: str
    request_id: str
    user_id: str
    claims: dict


_config = None
_table = None


class AppError(Exception):
    status_code = 500
    error_code = "internal_error"

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(AppError):
    status_code = 400
    error_code = "validation_error"


class UnauthorizedError(AppError):
    status_code = 401
    error_code = "unauthorized"


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"


def lambda_handler(event, context):
    print("Received HTTP API event:")
    print(json.dumps(event, default=str))

    try:
        route_key = get_route_key(event)
        request_context = build_request_context(event, route_key)
        handler = get_route_handler(route_key)

        result = handler(event, request_context)

        return create_response(
            status_code=200,
            body=result,
        )

    except AppError as error:
        print(f"Application error: {error.message}")

        return create_response(
            status_code=error.status_code,
            body={
                "message": error.message,
                "error_code": error.error_code,
                "details": error.details,
            },
        )

    except Exception as error:
        print(f"Unhandled error: {error}")

        return create_response(
            status_code=500,
            body={
                "message": "Internal server error",
                "error_code": "internal_error",
            },
        )


def get_route_handler(route_key: str):
    handlers = {
        "POST /query/tags": handle_query_tags,
        "GET /query/species": handle_query_species,
        "POST /query/thumbnail": handle_query_thumbnail,
        "POST /tags/bulk": handle_bulk_tags,
        "POST /files/delete": handle_delete_files,
    }

    handler = handlers.get(route_key)

    if not handler:
        raise NotFoundError(
            message=f"Unsupported route: {route_key}",
        )

    return handler


def handle_query_tags(event: dict, request_context: RequestContext) -> dict:
    body = parse_json_body(event)

    from query_service import find_files_by_tags

    return find_files_by_tags(
        body=body,
        request_context=request_context,
        config=get_config(),
        table=get_table(),
        s3_client=s3,
    )


def handle_query_species(event: dict, request_context: RequestContext) -> dict:
    species = get_required_query_param(event, "species")

    from query_service import find_files_by_species

    return find_files_by_species(
        species=species,
        request_context=request_context,
        config=get_config(),
        table=get_table(),
        s3_client=s3,
    )


def handle_query_thumbnail(event: dict, request_context: RequestContext) -> dict:
    body = parse_json_body(event)
    thumbnail_url = get_required_body_field(body, "thumbnail_url")

    from query_service import find_file_by_thumbnail_url

    return find_file_by_thumbnail_url(
        thumbnail_url=thumbnail_url,
        request_context=request_context,
        config=get_config(),
        table=get_table(),
        s3_client=s3,
    )


def handle_bulk_tags(event: dict, request_context: RequestContext) -> dict:
    body = parse_json_body(event)

    from tag_service import bulk_update_tags

    return bulk_update_tags(
        body=body,
        request_context=request_context,
        config=get_config(),
        table=get_table(),
    )


def handle_delete_files(event: dict, request_context: RequestContext) -> dict:
    body = parse_json_body(event)

    from delete_service import delete_files

    return delete_files(
        body=body,
        request_context=request_context,
        config=get_config(),
        table=get_table(),
        s3_client=s3,
    )


def load_config() -> AppConfig:
    media_bucket = os.environ.get("MEDIA_BUCKET")
    media_table = os.environ.get("MEDIA_TABLE")

    if not media_bucket:
        raise RuntimeError("Missing required environment variable: MEDIA_BUCKET")

    if not media_table:
        raise RuntimeError("Missing required environment variable: MEDIA_TABLE")

    return AppConfig(
        media_bucket=media_bucket,
        media_table=media_table,
        assets_prefix=os.environ.get("ASSETS_PREFIX", "assets/").strip("/"),
        presigned_url_expires_in=int(os.environ.get("PRESIGNED_URL_EXPIRES_IN", "3600")),
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


def get_route_key(event: dict) -> str:
    route_key = event.get("routeKey")

    if route_key:
        return route_key

    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}

    method = http.get("method")
    path = event.get("rawPath") or http.get("path")

    if not method or not path:
        raise ValidationError("Unable to resolve HTTP route")

    return f"{method} {path}"


def build_request_context(event: dict, route_key: str) -> RequestContext:
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    authorizer = request_context.get("authorizer") or {}
    jwt = authorizer.get("jwt") or {}
    claims = jwt.get("claims") or {}

    user_id = claims.get("sub")

    if not user_id:
        raise UnauthorizedError("Missing Cognito user identity")

    return RequestContext(
        route_key=route_key,
        method=http.get("method", ""),
        path=event.get("rawPath") or http.get("path", ""),
        request_id=request_context.get("requestId", ""),
        user_id=user_id,
        claims=claims,
    )


def parse_json_body(event: dict) -> Any:
    raw_body = event.get("body")

    if raw_body is None or raw_body == "":
        return {}

    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        return json.loads(raw_body, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise ValidationError("Request body must be valid JSON") from error


def get_required_query_param(event: dict, name: str) -> str:
    query_params = event.get("queryStringParameters") or {}
    value = query_params.get(name)

    if value is None or str(value).strip() == "":
        raise ValidationError(
            message=f"Missing required query parameter: {name}",
        )

    return str(value).strip()


def get_required_body_field(body: Any, name: str) -> Any:
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")

    value = body.get(name)

    if value is None or value == "":
        raise ValidationError(
            message=f"Missing required body field: {name}",
        )

    return value


def create_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, cls=DecimalEncoder, default=str),
    }


class DecimalEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, Decimal):
            if value % 1 == 0:
                return int(value)

            return float(value)

        return super().default(value)