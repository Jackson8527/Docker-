from fastapi import APIRouter, HTTPException, Query, Body

from app.services.docker import get_docker_client, extract_error, ContainerInfo

router = APIRouter(prefix="/api/containers", tags=["containers"])


def _info(cont) -> ContainerInfo:
    return ContainerInfo(
        id=cont.id,
        name=cont.name or "",
        image=cont.image.tags,
        state=cont.state,
        status=cont.status,
        ports=str(cont.ports or []),
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