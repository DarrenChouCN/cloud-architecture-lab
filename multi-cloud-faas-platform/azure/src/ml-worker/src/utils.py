from pathlib import Path
import base64
import shutil
import requests
import tempfile



def ensure_dir(path: str | Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_dir(path: str | Path) -> Path:
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_file_suffix(file_url: str, default: str = ".jpg") -> str:
    lower_url = file_url.lower()

    for suffix in [".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".avi"]:
        if suffix in lower_url:
            return suffix

    return default


def download_file_from_url(file_url: str, suffix: str = ".jpg") -> str:
    response = requests.get(file_url, timeout=120)
    response.raise_for_status()

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.write(response.content)
    temp_file.close()

    return temp_file.name


def encode_file_to_base64(file_path: str | Path) -> str:
    file_path = Path(file_path)

    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def build_success_response(**kwargs) -> dict:
    response = {
        "status": "success"
    }
    response.update(kwargs)
    return response


def build_error_response(message: str, **kwargs) -> dict:
    response = {
        "status": "error",
        "message": message
    }
    response.update(kwargs)
    return response