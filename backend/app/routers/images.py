from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.services.docker import get_docker_client, extract_error

router = APIRouter(prefix="/api/images", tags=["images"])

# Substrings that mean "the registry could not be reached", as opposed to
# "the image does not exist" or "authentication failed". Only these justify
# retrying through a mirror.
_UNREACHABLE_MARKERS = (
    "failed to resolve reference",
    "dial tcp",
    "connectex",
    "connection attempt failed",
    "no such host",
    "i/o timeout",
    "tls handshake timeout",
    "context deadline exceeded",
    "connection refused",
    "no https proxy",
    "registry-1.docker.io",
)


def _is_registry_unreachable(message: str) -> bool:
    low = (message or "").lower()
    return any(m in low for m in _UNREACHABLE_MARKERS)


def _is_docker_hub_ref(name: str) -> bool:
    """True when `name` refers to Docker Hub, explicitly or by default.

    Docker treats the first path segment as a registry host when it contains
    a dot or a colon, or is literally 'localhost'.
    """
    first = name.split("/")[0]
    if first == "docker.io":
        return True
    if "." in first or ":" in first or first == "localhost":
        return False
    return True


def _hub_path(name: str) -> str:
    """'mysql' -> 'library/mysql'; 'user/app' -> 'user/app'."""
    ref = name[len("docker.io/"):] if name.startswith("docker.io/") else name
    return ref if "/" in ref else f"library/{ref}"


def _canonical(name: str) -> str:
    """The name users expect to see locally, e.g. 'mysql' or 'user/app'."""
    ref = name[len("docker.io/"):] if name.startswith("docker.io/") else name
    if ref.startswith("library/"):
        return ref[len("library/"):]
    return ref


def _repo_digest(img) -> str:
    """The registry manifest digest, e.g. 'sha256:...'.

    This is NOT the image id: `img.short_id` is the config digest, so using it
    here made the Digest column an exact copy of the ID column. Locally built
    images have no RepoDigests and yield "".
    """
    digests = (getattr(img, "attrs", None) or {}).get("RepoDigests") or []
    if not digests:
        return ""
    return str(digests[0]).split("@")[-1]


@router.get("")
def list_images():
    try:
        return [
            {
                "id": img.id,
                "tags": img.tags,
                "digest": _repo_digest(img),
                "short_id": img.short_id.replace("sha256:", "")[:12],
            }
            for img in get_docker_client().images.list()
        ]
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.get("/pull/mirrors")
def pull_mirrors():
    """The mirror list, so the UI can explain what will be tried."""
    return {"mirrors": get_settings()["image_mirrors"]}


@router.get("/{iid}/save")
def save_image(iid: str):
    try:
        img = get_docker_client().images.get(iid)
        return StreamingResponse(img.save(), media_type="application/x-tar")
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.delete("/{iid}")
def remove_image(iid: str, force: bool = Query(False)):
    try:
        get_docker_client().images.remove(iid, force=force)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("/pull")
def pull(name: str = Body(...), tag: str = Body("latest")):
    """Pull an image, falling back to mirrors when Docker Hub is unreachable.

    Many networks cannot reach registry-1.docker.io at all. Rather than
    failing outright, a Hub reference is retried through each configured
    mirror and then re-tagged under the canonical name, so `docker run mysql`
    still works after pulling `mysql` here.
    """
    client = get_docker_client()
    name = (name or "").strip()
    tag = (tag or "latest").strip() or "latest"
    if not name:
        raise HTTPException(400, "镜像名不能为空")

    canonical = _canonical(name)

    # 1) Straight pull first: correct whenever the registry is reachable.
    try:
        client.images.pull(name, tag=tag)
        return {"ok": True, "image": f"{canonical}:{tag}", "source": "direct"}
    except Exception as e:
        direct_error = extract_error(e)

    # 2) Only a network failure justifies mirrors; a missing image or bad
    #    credentials must surface unchanged.
    if not _is_registry_unreachable(direct_error):
        raise HTTPException(500, direct_error)

    if not _is_docker_hub_ref(name):
        raise HTTPException(
            502,
            f"无法连接镜像仓库，且「{name}」不是 Docker Hub 镜像，"
            f"无法通过镜像源加速。\n\n原始错误：{direct_error}",
        )

    errors = [f"直连 Docker Hub：{direct_error}"]
    for mirror in get_settings()["image_mirrors"]:
        mirror_ref = f"{mirror}/{_hub_path(name)}"
        try:
            client.images.pull(mirror_ref, tag=tag)
        except Exception as e:
            errors.append(f"镜像源 {mirror}：{extract_error(e)}")
            continue

        # Re-tag under the canonical name so the image behaves normally,
        # then drop the mirror-specific tag (the image itself stays, since
        # the canonical tag still references it).
        try:
            img = client.images.get(f"{mirror_ref}:{tag}")
            img.tag(canonical, tag)
        except Exception as e:
            errors.append(f"镜像源 {mirror} 打标签失败：{extract_error(e)}")
            continue

        try:
            client.images.remove(f"{mirror_ref}:{tag}")
        except Exception:
            # Leaving the mirror tag behind is harmless.
            pass

        return {"ok": True, "image": f"{canonical}:{tag}", "source": mirror}

    raise HTTPException(
        502,
        "Docker Hub 不可达，并且所有镜像源都拉取失败。\n\n"
        + "\n".join(errors)
        + "\n\n可在 docker-compose.yml 的 IMAGE_MIRRORS 中配置其他镜像源。",
    )
