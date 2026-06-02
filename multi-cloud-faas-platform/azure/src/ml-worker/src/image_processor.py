from pathlib import Path
from PIL import Image
from megadetector.detection import run_detector_batch

import json
import shutil
import uuid

from src.model_service import classify_crops
from src.thumbnail import create_thumbnail
from src.utils import encode_file_to_base64

import os

"""
Image processing pipeline for the wildlife ML worker.

This module runs MegaDetector on an image, crops detected animal regions,
classifies the cropped regions with the species model, and generates thumbnail
data for the AWS backend.
"""

MD_MODEL_PATH = os.getenv("MD_MODEL_PATH", "./models/mdv5a.pt")
OUTPUT_ROOT = Path("./outputs")


def clear_temp_dir(temp_dir: Path):
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)


def run_megadetector_single_image(image_path: str, result_json_path: Path) -> list:
    data = run_detector_batch.load_and_run_detector_batch(
        image_file_names=[image_path],
        model_file=MD_MODEL_PATH
    )

    result_json_path.parent.mkdir(parents=True, exist_ok=True)

    with open(result_json_path, "w") as f:
        json.dump(data, f)

    return data

def run_megadetector_batch_images(image_paths: list[str], result_json_path: Path) -> list:
    """
    Run MegaDetector once on multiple images.
    This is used for video frames to avoid loading MegaDetector repeatedly.
    """
    result_json_path.parent.mkdir(parents=True, exist_ok=True)

    data = run_detector_batch.load_and_run_detector_batch(
        image_file_names=image_paths,
        model_file=MD_MODEL_PATH
    )

    with open(result_json_path, "w") as f:
        json.dump(data, f)

    return data

def crop_detected_animals(
    md_data: list,
    crop_dir: Path,
    conf_threshold: float = 0.05,
    snip_size: int = 600
) -> list[Path]:
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_paths = []

    for entry in md_data:
        img_path = entry["file"]

        if not Path(img_path).exists():
            continue

        detections = entry["detections"]
        img = Image.open(img_path).convert("RGB")
        W, H = img.size

        crop_num = 0

        for detection in detections:
            conf = detection["conf"]

            # MegaDetector category "1" means animal
            if detection["category"] != "1":
                continue

            if conf < conf_threshold:
                continue

            x, y, w, h = detection["bbox"]

            left = int(x * W)
            top = int(y * H)
            right = int((x + w) * W)
            bottom = int((y + h) * H)

            crop = img.crop((left, top, right, bottom))
            resized = crop.resize((snip_size, snip_size), Image.BILINEAR)

            out_name = f"{Path(img_path).stem}-{crop_num}{Path(img_path).suffix}"
            out_path = crop_dir / out_name

            resized.save(out_path)
            crop_paths.append(out_path)

            crop_num += 1

    return crop_paths


def process_image(image_path: str, file_id: str | None = None) -> dict:
    if file_id is None:
        file_id = str(uuid.uuid4())

    run_dir = OUTPUT_ROOT / "runtime" / file_id
    crop_dir = run_dir / "crops"
    result_json_path = run_dir / "mg_detections.json"

    clear_temp_dir(run_dir)
    crop_dir.mkdir(parents=True, exist_ok=True)

    md_data = run_megadetector_single_image(image_path, result_json_path)

    crop_paths = crop_detected_animals(
        md_data=md_data,
        crop_dir=crop_dir,
        conf_threshold=0.05,
        snip_size=600
    )

    tags = classify_crops(crop_paths)

    thumbnail_path = create_thumbnail(image_path)
    thumbnail_base64 = encode_file_to_base64(thumbnail_path)

    return {
        "file_id": file_id,
        "status": "success",
        "tags": tags,
        "thumbnail": {
            "content_type": "image/jpeg",
            "data_base64": thumbnail_base64
        },
        "thumbnail_path": str(thumbnail_path),
        "crops_count": len(crop_paths)
    }