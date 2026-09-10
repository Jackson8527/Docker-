from functools import lru_cache
import os


@lru_cache
def get_settings() -> dict:
    return {
        "docker_host": os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"),
        "port": int(os.environ.get("PORT", "8088")),
        "tmp_dir": os.environ.get("TMP_DIR", "/tmp/dockermgr"),
    }