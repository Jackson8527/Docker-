from fastapi import APIRouter, HTTPException, Body

from app.services.docker import get_docker_client, extract_error

router = APIRouter(prefix="/api/volumes", tags=["volumes"])


@router.get("")
def list_volumes():
    try:
        return [
            {
                "name": v.name,
                "driver": v.attrs.get("Driver", ""),
                "mountpoint": v.attrs.get("Mountpoint", ""),
            }
            for v in get_docker_client().volumes.list()
        ]
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("")
def create_volume(name: str = Body(...)):
    try:
        get_docker_client().volumes.create(name)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.delete("/{vid}")
def delete_volume(vid: str):
    try:
        get_docker_client().volumes.get(vid).remove()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))