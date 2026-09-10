from fastapi import APIRouter, HTTPException, Body

from app.services.docker import get_docker_client, extract_error

router = APIRouter(prefix="/api/networks", tags=["networks"])


@router.get("")
def list_networks():
    try:
        return [
            {
                "id": n.id,
                "name": n.name,
                "driver": n.attrs.get("Driver", ""),
                "scope": n.attrs.get("Scope", ""),
            }
            for n in get_docker_client().networks.list()
        ]
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.post("")
def create_network(name: str = Body(...), driver: str = Body("bridge")):
    try:
        get_docker_client().networks.create(name, driver=driver)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.delete("/{nid}")
def delete_network(nid: str):
    try:
        get_docker_client().networks.get(nid).remove()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))