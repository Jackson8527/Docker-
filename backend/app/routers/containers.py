from fastapi import APIRouter, HTTPException, Query, Body

from app.services.docker import get_docker_client, extract_error, ContainerInfo

router = APIRouter(prefix="/api/containers", tags=["containers"])


def _format_ports(ports) -> str:
    """Render docker-py's ports mapping as human-readable text.

    docker-py gives {'80/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8088'}]};
    the UI wants '8088->80/tcp'. Exposed-only ports keep their bare form.
    """
    if not ports:
        return ""
    parts = []
    for container_port, bindings in ports.items():
        if not bindings:
            parts.append(str(container_port))
            continue
        for b in bindings:
            host_ip = (b or {}).get("HostIp") or ""
            host_port = (b or {}).get("HostPort") or ""
            prefix = f"{host_ip}:" if host_ip and host_ip not in ("0.0.0.0", "::") else ""
            parts.append(f"{prefix}{host_port}->{container_port}")
    return ", ".join(parts)


def _info(cont) -> ContainerInfo:
    """Map a docker-py Container to our API model.

    NOTE: docker-py Container has no `.state` attribute; state lives in
    `attrs["State"]["Status"]` (and `.status` mirrors it). Image tags is a
    list, so we surface the first tag as the display image name.
    """
    state_obj = cont.attrs.get("State", {}) or {}
    tags = (cont.image.tags if cont.image else None) or []
    return ContainerInfo(
        id=cont.id,
        name=(cont.name or "").lstrip("/"),
        image=tags[0] if tags else "",
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