import os
import traceback
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.model_downloader import ensure_models_downloaded
from src.image_processor import process_image
from src.video_processor import process_video
from src.utils import download_file_from_url, get_file_suffix

"""
FastAPI entry point for the Azure ML worker.

This service is deployed on Azure Container Apps. It receives file URLs from
the AWS backend, downloads the media file, runs the wildlife detection and
species classification pipeline, and returns JSON results.

The actual model files are not packaged inside the Docker image. They are
downloaded from Azure Blob Storage when the container starts.
"""

# Fix protobuf compatibility issue for onnx / onnx2torch
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

app = FastAPI(
    title="Wildlife ML Worker",
    description="Container-based Azure ML/media processing worker for FIT5225 A2.",
    version="1.0.0"
)


class ProcessMediaRequest(BaseModel):
    file_id: str
    file_type: Literal["image", "video"]
    file_url: str
    model_version: Optional[str] = "v1"


class AnalyzeQueryFileRequest(BaseModel):
    query_id: str
    file_type: Literal["image", "video"]
    file_url: str
    model_version: Optional[str] = "v1"


@app.on_event("startup")
def startup_event():
    """
        Ensure the required model files are available before accepting requests.
        In the cloud environment, the container downloads the model artifacts from
        Azure Blob Storage during startup.
    """
    ensure_models_downloaded()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_version": os.getenv("MODEL_VERSION", "v1"),
        "model_loaded": True,
        "runtime": "python",
        "service": "Azure Container Wildlife ML Worker"
    }


@app.post("/process-image")
def process_image_endpoint(request: ProcessMediaRequest):
    """
    Process an uploaded image file.

    AWS sends a temporary file URL, usually a presigned S3 URL. This endpoint
    downloads the image, runs detection/classification, generates a thumbnail,
    and returns tags and thumbnail data.
    """
    try:
        suffix = get_file_suffix(request.file_url, default=".jpg")
        local_path = download_file_from_url(request.file_url, suffix=suffix)

        result = process_image(
            image_path=local_path,
            file_id=request.file_id
        )

        result["model_version"] = request.model_version
        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": str(e),
                "trace": traceback.format_exc()
            }
        )


@app.post("/process-video")
def process_video_endpoint(request: ProcessMediaRequest):
    """
    Process an uploaded video file.

    The video is downloaded from the given URL. The worker extracts one frame
    per second, detects animals in the frames, classifies detected crops, and
    returns aggregated species counts.
    """
    try:
        suffix = get_file_suffix(request.file_url, default=".mp4")
        local_path = download_file_from_url(request.file_url, suffix=suffix)

        result = process_video(
            video_path=local_path,
            file_id=request.file_id
        )

        result["model_version"] = request.model_version
        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": str(e),
                "trace": traceback.format_exc()
            }
        )


@app.post("/analyze-query-file")
def analyze_query_file_endpoint(request: AnalyzeQueryFileRequest):
    """
    Analyze a temporary query file.

    This endpoint is used for query-by-file. It returns detected tags only and
    does not permanently store the uploaded query file.
    """
    try:
        if request.file_type == "image":
            suffix = get_file_suffix(request.file_url, default=".jpg")
            local_path = download_file_from_url(request.file_url, suffix=suffix)

            result = process_image(
                image_path=local_path,
                file_id=request.query_id
            )

            return {
                "query_id": request.query_id,
                "status": "success",
                "file_type": "image",
                "tags": result.get("tags", {}),
                "model_version": request.model_version
            }

        if request.file_type == "video":
            suffix = get_file_suffix(request.file_url, default=".mp4")
            local_path = download_file_from_url(request.file_url, suffix=suffix)

            result = process_video(
                video_path=local_path,
                file_id=request.query_id
            )

            return {
                "query_id": request.query_id,
                "status": "success",
                "file_type": "video",
                "tags": result.get("tags", {}),
                "frames_processed": result.get("frames_processed", 0),
                "model_version": request.model_version
            }

        raise HTTPException(
            status_code=400,
            detail="file_type must be either image or video"
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": str(e),
                "trace": traceback.format_exc()
            }
        )