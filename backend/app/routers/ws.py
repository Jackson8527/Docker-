from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import asyncio
import json
import logging
import socket
import threading

from app.services.docker import get_docker_client

router = APIRouter()
logger = logging.getLogger("dockermgr.ws")


def _find_container(name: str):
    """Match the first running container by name prefix; None if not found."""
    for c in get_docker_client().containers.list():
        if c.name.startswith(name):
            return c
    return None


def _raw_socket(output):
    """docker-py may hand back a SocketIO wrapper or a bare socket.

    The wrapper exposes `_sock` and HAS NO settimeout()/setblocking(), so all
    socket-level calls must go through the underlying real socket.
    """
    return getattr(output, "_sock", output)


def _send_from_thread(loop, ws: WebSocket, text: str) -> None:
    """Schedule a websocket send from a worker thread onto the event loop."""
    loop.call_soon_threadsafe(_dispatch_send, ws, text)


def _dispatch_send(ws: WebSocket, text: str) -> None:
    """Runs on the event-loop thread, so ensure_future is safe here."""
    asyncio.ensure_future(_safe_send(ws, text))


async def _safe_send(ws: WebSocket, text: str) -> None:
    try:
        await ws.send_text(text)
    except Exception:
        pass


async def _close_ws(ws: WebSocket) -> None:
    """Close only if the client is still connected; never raise."""
    try:
        if ws.client_state != WebSocketState.DISCONNECTED:
            await ws.close()
    except Exception:
        pass


@router.websocket("/ws/logs")
async def ws_logs(ws: WebSocket, filter: str = "", stream: str = "stdout", tail: int = 100):
    """Stream container logs to the client.

    IMPORTANT: docker-py's `logs(follow=True)` returns a BLOCKING generator.
    Iterating it inside the async handler freezes uvicorn's event loop (and
    with it the entire API) the moment the container goes quiet, because
    `next()` blocks on the docker socket read indefinitely. The blocking read
    therefore runs on a worker thread and pushes lines back to the loop via
    call_soon_threadsafe.
    """
    await ws.accept()
    stop = threading.Event()
    log_stream = None
    try:
        cont = await asyncio.to_thread(_find_container, filter)
        if cont is None:
            await ws.send_json({"error": "no container"})
            await ws.close()
            return

        loop = asyncio.get_event_loop()
        log_stream = cont.logs(
            stream=True,
            follow=True,
            stdout=stream in ("stdout", "both"),
            stderr=stream in ("stderr", "both"),
            tail=tail,
        )

        def pump():
            """Blocking reader; must never touch the event loop directly."""
            try:
                for line in log_stream:
                    if stop.is_set():
                        break
                    _send_from_thread(loop, ws, line.decode("utf-8", errors="replace"))
            except Exception:
                logger.debug("log stream reader stopped", exc_info=True)
            finally:
                loop.call_soon_threadsafe(stop.set)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()

        # Stay responsive while the stream runs: wait for a client disconnect
        # with a bounded timeout instead of blocking on the log reader.
        while not stop.is_set():
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_logs failed for filter=%r", filter)
    finally:
        stop.set()
        if log_stream is not None:
            try:
                # Closes the underlying socket, unblocking the reader thread.
                log_stream.close()
            except Exception:
                pass
        await _close_ws(ws)


@router.websocket("/ws/exec")
async def ws_exec(ws: WebSocket, container: str, cmd: str = "/bin/sh"):
    """Interactive terminal over websocket.

    Client -> server frames are JSON control messages:
        {"type": "input",  "data": "<keystrokes>"}
        {"type": "resize", "cols": 120, "rows": 30}
    (Plain text frames are still accepted as raw input for compatibility.)

    Server -> client frames are raw terminal bytes.

    The exec is created through the low-level API rather than
    `containers.exec_run()` so the exec id stays available: without it we
    could not resize the PTY, and an 80x24 PTY inside a wider browser
    terminal wraps every line at the wrong column.
    """
    await ws.accept()
    raw = None
    stop = threading.Event()
    reader = None
    api = None
    exec_id = None
    try:
        client = get_docker_client()
        api = client.api
        cont = await asyncio.to_thread(client.containers.get, container)

        spec = await asyncio.to_thread(
            api.exec_create,
            cont.id,
            [cmd],
            stdin=True,   # REQUIRED: without it the daemon discards all input
            tty=True,
            stdout=True,
            stderr=True,
        )
        exec_id = spec["Id"]
        output = await asyncio.to_thread(api.exec_start, exec_id, tty=True, socket=True)
        raw = _raw_socket(output)
        raw.setblocking(True)
        # Short timeout so the reader thread stays interruptible on shutdown.
        raw.settimeout(0.2)

        loop = asyncio.get_event_loop()

        # Background thread: docker socket -> websocket.
        def read_sock():
            try:
                while not stop.is_set():
                    try:
                        data = raw.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not data:
                        break
                    _send_from_thread(loop, ws, data.decode("utf-8", errors="replace"))
            except Exception:
                logger.debug("exec socket reader stopped", exc_info=True)

        reader = threading.Thread(target=read_sock, daemon=True)
        reader.start()

        # Main coroutine: websocket -> docker socket.
        while True:
            message = await ws.receive_text()
            try:
                payload = json.loads(message)
            except (ValueError, TypeError):
                payload = None

            if not isinstance(payload, dict):
                # Legacy raw-text frame: treat the whole frame as input.
                raw.send(message.encode())
                continue

            mtype = payload.get("type")
            if mtype == "input":
                raw.send(str(payload.get("data", "")).encode())
            elif mtype == "resize":
                cols = int(payload.get("cols") or 0)
                rows = int(payload.get("rows") or 0)
                if cols > 0 and rows > 0:
                    try:
                        await asyncio.to_thread(
                            api.exec_resize, exec_id, height=rows, width=cols
                        )
                    except Exception:
                        # A failed resize must never kill the session.
                        logger.debug("exec_resize failed", exc_info=True)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_exec failed for container=%r", container)
    finally:
        stop.set()
        if reader is not None:
            reader.join(timeout=1)
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass
        await _close_ws(ws)
