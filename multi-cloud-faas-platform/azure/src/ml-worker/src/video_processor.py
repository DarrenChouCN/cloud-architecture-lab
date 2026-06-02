from pathlib import Path
import uuid
import cv2

from src.image_processor import (
    run_megadetector_batch_images,
    crop_detected_animals
)
from src.model_service import classify_crops
from src.utils import clean_dir

"""
Video processing pipeline for the wildlife ML worker.

Videos are processed by extracting one frame per second. This reduces the
amount of data processed while still following the assignment requirement.
The extracted frames are then handled using the same detection and
classification logic as images.
"""

OUTPUT_ROOT = Path("./outputs")


def extract_one_frame_per_second(video_path: str, output_dir: str | Path) -> list[Path]:
    """
    Extract one frame per second from the input video.

    The assignment requires 1 FPS extraction instead of processing every video
    frame, which reduces processing time and resource usage.
    """
    output_dir = clean_dir(output_dir)

    video = cv2.VideoCapture(video_path)

    if not video.isOpened():
        raise ValueError(f"Cannot open video file: {video_path}")

    fps = video.get(cv2.CAP_PROP_FPS)

    if fps <= 0:
        fps = 25

    frame_interval = int(fps)

    frame_paths = []
    frame_index = 0
    saved_index = 0

    while True:
        success, frame = video.read()

        if not success:
            break

        if frame_index % frame_interval == 0:
            frame_path = output_dir / f"frame_{saved_index:04d}.jpg"
            cv2.imwrite(str(frame_path), frame)
            frame_paths.append(frame_path)
            saved_index += 1

        frame_index += 1

    video.release()

    return frame_paths


def process_video(video_path: str, file_id: str | None = None) -> dict:
    """
    Process a video by extracting 1 frame per second, running MegaDetector once
    on all frames, classifying all detected animal crops, and returning merged tags.
    """
    if file_id is None:
        file_id = str(uuid.uuid4())

    run_dir = OUTPUT_ROOT / "runtime" / file_id
    frame_dir = run_dir / "frames"
    crop_dir = run_dir / "crops"
    result_json_path = run_dir / "mg_detections_video.json"

    clean_dir(run_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    frame_paths = extract_one_frame_per_second(
        video_path=video_path,
        output_dir=frame_dir
    )

    if not frame_paths:
        return {
            "file_id": file_id,
            "status": "success",
            "file_type": "video",
            "tags": {},
            "frames_processed": 0,
            "crops_count": 0
        }

    frame_path_strings = [str(path) for path in frame_paths]

    # Important optimization:
    # run MegaDetector once on all extracted frames
    md_data = run_megadetector_batch_images(
        image_paths=frame_path_strings,
        result_json_path=result_json_path
    )

    # Crop all detected animals from all frames
    crop_paths = crop_detected_animals(
        md_data=md_data,
        crop_dir=crop_dir,
        conf_threshold=0.05,
        snip_size=600
    )

    # Classify all crops once
    tags = classify_crops(
        crop_paths=crop_paths,
        min_confidence=0.7
    )

    return {
        "file_id": file_id,
        "status": "success",
        "file_type": "video",
        "tags": tags,
        "frames_processed": len(frame_paths),
        "crops_count": len(crop_paths)
    }