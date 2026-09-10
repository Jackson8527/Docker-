from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from docker.errors import ImageNotFound

from app.services.docker import get_docker_client, extract_error, ContainerInfo
from app.services.run_spec import build_run_kwargs

router = APIRouter(prefix="/api/containers", tags=["containers"])


class RunRequest(BaseModel):
    """Free-text description of a container to create from an image."""

    image: str
    name: str | None = None
    ports: str | None = None
    env: str | None = None
    volumes: str | None = None
    command: str | None = None
    restart_policy: str | None = None
    auto_start: bool = True


def _append_unique(parts: list, value: str) -> None:
    if value not in parts:
        parts.append(value)


def _format_ports(ports) -> str:
    """Render docker-py's ports mapping as human-readable text.

    docker-py gives {'80/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8088'}]};
    the UI wants '8088->80/tcp'. Exposed-only ports keep their bare form.

    A published port normally comes back twice - once bound to 0.0.0.0 and
    once to :: - and both render identically, so duplicates are collapsed.
    """
    if not ports:
        return ""
    parts: list[str] = []
    for container_port, bindings in ports.items():
        if not bindings:
            _append_unique(parts, str(container_port))
            continue
        for b in bindings:
            host_ip = (b or {}).get("HostIp") or ""
            host_port = (b or {}).get("HostPort") or ""
            prefix = f"{host_ip}:" if host_ip and host_ip not in ("0.0.0.0", "::") else ""
            _append_unique(parts, f"{prefix}{host_port}->{container_port}")
    return ", ".join(parts)


def _image_name(cont) -> str:
    """Best available image label for a container.

    Current tags are the most accurate label, but reading them costs an API
    lookup that raises when the image has been deleted. A container left
    pointing at a removed image (a dangling reference) must not take the whole
    listing down with it, so fall back to data already in the container attrs.
    """
    try:
        tags = (cont.image.tags if cont.image else None) or []
        if tags:
            return tags[0]
    except Exception:
        pass

    # Recorded at creation time; needs no extra API call.
    config_image = (cont.attrs.get("Config") or {}).get("Image")
    if config_image:
        return config_image

    return (cont.attrs.get("Image") or "").replace("sha256:", "")[:12]


def _info(cont) -> ContainerInfo:
    """Map a docker-py Container to our API model.

    NOTE: docker-py Container has no `.state` attribute; state lives in
    `attrs["State"]["Status"]` (and `.status` mirrors it).
    """
    state_obj = cont.attrs.get("State", {}) or {}
    return ContainerInfo(
        id=cont.id,
        name=(cont.name or "").lstrip("/"),
        image=_image_name(cont),
        state=state_obj.get("Status", "") or cont.status,
        status=cont.status,
        ports=_format_ports(cont.ports),
        created=cont.attrs.get("Created", ""),
    )


@router.get("")
def list_containers(all: bool = Query(False)):
    try:
        return [_info(c) for c in get_docker_client().containers.list(all=all)]
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("")
def create_container(payload: RunRequest = Body(...)):
    """Create a container from an image, optionally starting it right away."""
    try:
        kwargs = build_run_kwargs(
            image=payload.image,
            name=payload.name,
            ports=payload.ports,
            env=payload.env,
            volumes=payload.volumes,
            command=payload.command,
            restart_policy=payload.restart_policy,
        )
    except ValueError as e:
        # Malformed form input: safe and useful to show verbatim.
        raise HTTPException(400, str(e))

    client = get_docker_client()

    # Fail early with an actionable message instead of a daemon error.
    try:
        client.images.get(payload.image)
    except ImageNotFound:
        raise HTTPException(
            404, f"镜像「{payload.image}」不存在，请先到镜像页拉取。"
        )
    except Exception as e:
        raise HTTPException(500, extract_error(e))

    kwargs["detach"] = True
    try:
        if payload.auto_start:
            cont = client.containers.run(**kwargs)
        else:
            cont = client.containers.create(**kwargs)
    except Exception as e:
        message = extract_error(e)
        low = message.lower()
        if "port is already allocated" in low or "address already in use" in low:
            raise HTTPException(409, f"端口已被占用：{message}")
        if "already in use by container" in message:
            raise HTTPException(409, f"容器名已被占用：{message}")
        raise HTTPException(500, message)

    try:
        cont.reload()
    except Exception:
        # A stale view is better than failing a container that did start.
        pass
    return _info(cont)


@router.get("/{cid}")
def inspect(cid: str):
    try:
        return _info(get_docker_client().containers.get(cid))
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("/{cid}/start")
def start(cid: str):
    try:
        get_docker_client().containers.get(cid).start()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("/{cid}/stop")
def stop(cid: str):
    try:
        get_docker_client().containers.get(cid).stop()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("/{cid}/restart")
def restart(cid: str):
    try:
        get_docker_client().containers.get(cid).restart()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("/{cid}/pause")
def pause(cid: str):
    try:
        get_docker_client().containers.get(cid).pause()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("/{cid}/unpause")
def unpause(cid: str):
    try:
        get_docker_client().containers.get(cid).unpause()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.delete("/{cid}")
def remove(cid: str, force: bool = Query(False)):
    try:
        get_docker_client().containers.get(cid).remove(force=force)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("/{cid}/commit")
def commit(cid: str, repo: str = Body(...), tag: str = Body("latest")):
    try:
        img = get_docker_client().containers.get(cid).commit(repository=repo, tag=tag)
        return {"image_id": img.id}
    except Exception as e:
        raise HTTPException(500, extract_error(e))