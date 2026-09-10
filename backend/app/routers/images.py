from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import StreamingResponse

from app.services.docker import get_docker_client, extract_error

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("")
def list_images():
    try:
        return [
            {"id": img.id, "tags": img.tags, "digest": img.short_id}
            for img in get_docker_client().images.list()
        ]
    except Exception as e:
        raise HTTPException(500, extract_error(e))


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
    try:
        get_docker_client().images.pull(name, tag=tag)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))