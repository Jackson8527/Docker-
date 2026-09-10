from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.docker import get_docker_client

router = APIRouter()


def _stream_container(name: str):
    """Match the first running container by name prefix; None if not found."""
    for c in get_docker_client().containers.list():
        if c.name.startswith(name):
            return c
    return None


@router.websocket("/ws/logs")
async def ws_logs(ws: WebSocket, filter: str = "", stream: str = "stdout", tail: int = 100):
    await ws.accept()
    try:
        cont = _stream_container(filter)
        if cont is None:
            await ws.send_json({"error": "no container"})
            await ws.close()
            return

        def gen():
            return cont.logs(stream=True, follow=True,
                             stdout=stream in ("stdout", "both"),
                             stderr=stream in ("stderr", "both"),
                             tail=tail)

        for line in gen():
            await ws.send_text(line.decode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    except Exception:
        await ws.close()