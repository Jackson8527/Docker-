from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import socket
import threading

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


@router.websocket("/ws/exec")
async def ws_exec(ws: WebSocket, container: str):
    """Interactive terminal: docker exec tty, bidirectional over websocket."""
    await ws.accept()
    exec_inst = None
    sock = None
    stop = threading.Event()
    try:
        cont = get_docker_client().containers.get(container)
        exec_inst = cont.exec_run(["sh"], tty=True, socket=True, stream=True)
        sock = exec_inst.output

        loop = asyncio.get_event_loop()
        sock._sock.setblocking(True)
        sock.settimeout(0.2)

        # Background thread: read bytes from docker socket -> websocket.
        def read_sock():
            try:
                while not stop.is_set():
                    try:
                        data = sock._sock.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not data:
                        break
                    loop.call_soon_threadsafe(
                        _schedule_send, ws, data.decode("utf-8", errors="replace")
                    )
            except Exception:
                pass

        reader = threading.Thread(target=read_sock, daemon=True)
        reader.start()

        # Main coroutine: receive from websocket -> write into docker socket.
        while True:
            data = await ws.receive_text()
            if sock is None:
                break
            try:
                sock._sock.send(data.encode())
            except OSError:
                break

        stop.set()
        reader.join(timeout=1)
    except WebSocketDisconnect:
        pass
    except Exception:
        await ws.close()
    finally:
        stop.set()
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        try:
            if not ws.client_state.closed:
                await ws.close()
        except Exception:
            pass


def _schedule_send(ws: WebSocket, text: str):
    """Create a task to send text to the websocket from the event loop."""
    async def _do():
        try:
            await ws.send_text(text)
        except Exception:
            pass
    import asyncio as _a
    ts = _a.all_tasks()
    _ = ts
    loop = _a.get_event_loop()
    try:
        loop.create_task(_do())
    except Exception:
        pass