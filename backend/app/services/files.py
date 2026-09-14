import logging
import shutil
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("dockermgr.files")


def get_tmp_dir() -> Path:
    d = Path(get_settings()["tmp_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear_tmp_dir():
    """Empty the staging directory at startup.

    Files *and* directories: the spec says the directory is emptied on boot, so
    a leftover subdirectory must not survive either.
    """
    d = get_tmp_dir()
    for p in d.iterdir():
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        except OSError:
            # A staging entry we cannot delete must not stop the app from
            # booting - but it must not vanish silently either, otherwise a
            # leftover that keeps reappearing has no trace anywhere.
            logger.warning("failed to clear staging entry %s", p, exc_info=True)