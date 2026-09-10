import docker
from dataclasses import dataclass

from app.config import get_settings


@dataclass
class ContainerInfo:
    id: str
    name: str
    image: str
    state: str
    status: str
    ports: str
    created: str


@dataclass
class ImageInfo:
    id: str
    tags: list
    size: int


@dataclass
class NetworkInfo:
    id: str
    name: str
    driver: str
    scope: str


@dataclass
class VolumeInfo:
    name: str
    driver: str
    mountpoint: str


_client: docker.DockerClient | None = None


def get_docker_client() -> docker.DockerClient:
    global _client
    if _client is None:
        try:
            _client = docker.from_env()
        except Exception:
            _client = docker.DockerClient(base_url=get_settings()["docker_host"])
    return _client


def extract_error(e) -> str:
    msg = str(e)
    return msg.splitlines()[0] if msg else "Unknown docker error"