from pathlib import Path

from app.config import get_settings


def get_tmp_dir() -> Path:
    d = Path(get_settings()["tmp_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear_tmp_dir():
    d = get_tmp_dir()
    for p in d.iterdir():
        if p.is_file():
            p.unlink(missing_ok=True)