from functools import lru_cache
import os

# Registries tried, in order, when Docker Hub itself cannot be reached.
# Override with a comma-separated IMAGE_MIRRORS environment variable.
DEFAULT_IMAGE_MIRRORS = "docker.m.daocloud.io,docker.1panel.live"


@lru_cache
def get_settings() -> dict:
    return {
        "docker_host": os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"),
        "port": int(os.environ.get("PORT", "8088")),
        "tmp_dir": os.environ.get("TMP_DIR", "/tmp/dockermgr"),
        "image_mirrors": [
            m.strip().rstrip("/")
            for m in os.environ.get("IMAGE_MIRRORS", DEFAULT_IMAGE_MIRRORS).split(",")
            if m.strip()
        ],
    }
