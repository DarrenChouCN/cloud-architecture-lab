from pathlib import Path
from PIL import Image

"""
Thumbnail generation utilities.

Thumbnails are smaller preview versions of uploaded images. They are returned
to AWS as base64 data so that AWS can store them in S3 and display them in the
frontend without loading full-size images.
"""

def create_thumbnail(image_path: str, output_dir: str = "./outputs/thumbnails", max_size=(300, 300)) -> Path:
    """
    Create a compressed thumbnail while keeping the original aspect ratio.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    image_path = Path(image_path)
    img = Image.open(image_path).convert("RGB")
    img.thumbnail(max_size)

    output_path = output_dir / f"{image_path.stem}_thumb.jpg"
    img.save(output_path, "JPEG", quality=85)

    return output_path