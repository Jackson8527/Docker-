from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import asyncio
import json
import logging
import socket
import threading

import docker

from app.services.docker import extract_error, get_docker_client
from app.services.security import is_same_site

router = APIRouter()
logger = logging.getLogger("dockermgr.ws")

# Container logs are coalesced: one frame per flush interval instead of one
# frame per line. The previous code created an `ensure_future` per line with no
# backpressure at all, which is exactly what spec.md §6 asks to throttle. The
# buffer behind that throttle is bounded and drops the OLDEST lines once it is
# full, so a client that cannot keep up still ends up with the most recent
# output instead of losing the newest lines together with the old ones.
LOG_FLUSH_INTERVAL = 0.1
LOG_MAX_PENDING_LINES = 2000

# How long the handler waits for a client frame before looking at the producer
# state again. This is also the upper bound on how long an unopenable log stream
# takes to turn into an error frame, because the receive loop is where that
# failure is noticed.
LOG_POLL_INTERVAL = 0.5

# Every "this socket cannot be served" text frame carries the discriminator
# below. Without it a container that logs a single JSON line such as
# {"error": "upstream timeout"} would be parsed as a protocol frame by the
# client and swallowed instead of rendered. The frontend (utils/ws.ts) and
# scripts/e2e_verify.py key on the same field, so all three layers agree.
ERROR_FRAME_KIND = "error"


async def _send_error_frame(ws: WebSocket, reason: str) -> None:
    """Send the failure frame (never silent) BEFORE the socket is closed."""
    await ws.send_json({"dockermgr": ERROR_FRAME_KIND, "error": reason})


def _safe_reason(e: Exception) -> str:
    """Render an exception for the user without ever raising.

    `extract_error` calls `str(e)`, and docker-py's `__str__` dereferences the
    HTTP response object. If that fails we would fall through to the generic
    handler and close with zero frames - the exact silent close this endpoint is
    supposed to stop doing. So the message extraction is guarded as well.
    """
    try:
        return extract_error(e)
    except Exception:
        return type(e).__name__


def _find_container(name: str):
    """Match the first container by name prefix; None if not found.

    Running containers win, but a stopped/exited container is still a valid
    target: its logs are exactly what you want to read after something crashed.
    """
    client = get_docker_client()
    for list_all in (False, True):
        for c in client.containers.list(all=list_all):
            if c.name.startswith(name):
                return c
    return None


def _raw_socket(output):
    """docker-py may hand back a SocketIO wrapper or a bare socket.

    The wrapper exposes `_sock` and HAS NO settimeout()/setblocking(), so all
    socket-level calls must go through the underlying real socket.
    """
    return getattr(output, "_sock", output)


def _open_log_stream(cont, stream: str, tail: int):
    """Open the follow-stream - the blocking half of `/ws/logs`.

    `containers.logs(follow=True)` is NOT a lazy generator: docker-py sends the
    HTTP request (and, through `_check_is_tty`, a synchronous inspect) on the
    *calling* thread before it hands anything back to iterate. Calling it from
    the event loop therefore froze every other request and websocket for as long
    as the daemon took to answer. It runs on the producer thread instead, the
    same way `files._stage_and_push` keeps the docker calls off the loop.
    """
    return cont.logs(
        stream=True,
        follow=True,
        stdout=stream in ("stdout", "both"),
        stderr=stream in ("stderr", "both"),
        tail=tail,
    )


def _close_stream(stream) -> None:
    """Close a log stream if one was ever opened; never raise.

    Closing also unblocks the producer thread parked in `next()` - which is the
    only way a follow-stream on an idle container ever ends.
    """
    if stream is None:
        return
    try:
        stream.close()
    except Exception:
        pass


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

    IMPORTANT: BOTH blocking halves of docker-py's follow-stream run on a worker
    thread, never on the event loop:
      * OPENING it - `containers.logs()` issues its HTTP request (and, through
        `_check_is_tty`, a synchronous inspect) on the calling thread before it
        returns anything to iterate, so calling it here froze the whole API for
        as long as the daemon took to answer (RD3-02);
      * ITERATING it - `next()` parks on the docker socket until the container
        logs something, so an idle container froze the whole API indefinitely.
    The producer thread pushes lines back to the loop via call_soon_threadsafe;
    the async side only sends frames and owns the lifecycle.
    """
    if not is_same_site(ws.headers.get("origin"), ws.headers.get("host")):
        logger.warning(
            "rejected cross-site log websocket (origin=%r)", ws.headers.get("origin")
        )
        await ws.close(code=1008)
        return

    await ws.accept()
    stop = threading.Event()
    log_stream = None
    try:
        cont = await asyncio.to_thread(_find_container, filter)
        if cont is None:
            await _send_error_frame(ws, "no container")
            await ws.close()
            return

        loop = asyncio.get_event_loop()
        # Written by the producer thread, read by the receive loop below. Only a
        # failure to OPEN the stream lands here: at that point not one byte has
        # reached the client, so it is still reportable as an error frame. A
        # stream that dies mid-flight has already sent frames and is reported
        # the way it always was - by the socket closing.
        failure: list[str] = []

        def pump() -> None:
            """Blocking producer: opens the stream, then reads it forever.

            Nothing in here may touch the event loop directly, and the two
            blocking calls live here on purpose:
              * `_open_log_stream` - docker-py does its HTTP work on the calling
                thread before it returns anything (RD3-02);
              * `next()` on the follow-stream - parks on the docker socket until
                the container logs something.
            Lines are buffered here and flushed by a separate timer thread. A
            flush performed inside this loop would never happen on an idle
            container: `__next__` blocks, so one buffered line would sit unsent
            until the *next* line arrived.
            """
            nonlocal log_stream
            pending: list[str] = []
            lock = threading.Lock()
            counter = {"dropped": 0}
            finished = threading.Event()
            timer = None

            def flush() -> None:
                """Send everything buffered so far; safe to call from any thread.

                The lock covers the buffer swap only: sending is scheduled on
                the event loop *outside* it, so the timer thread never blocks
                behind the reader thread.
                """
                with lock:
                    if not pending and not counter["dropped"]:
                        return
                    lines: list[str] = []
                    if counter["dropped"]:
                        # The notice is its own list element, so `"\n".join`
                        # cannot glue it onto the first buffered line, and it
                        # carries no newline of its own. A frame may still start
                        # or end with an empty line - but only when the container
                        # really logged an empty line: those are preserved
                        # verbatim rather than silently filtered out.
                        lines.append(
                            f"... {counter['dropped']} lines dropped "
                            "(client too slow) ..."
                        )
                        counter["dropped"] = 0
                    lines.extend(pending)
                    pending.clear()
                    chunk = "\n".join(lines)
                _send_from_thread(loop, ws, chunk)

            def flusher() -> None:
                """Timer thread: flush on every interval, but NEVER on shutdown.

                `Event.wait` returns True when the event was set, so this loop
                leaves immediately once `finished` is set and does not flush a
                second time on its way out. The final flush therefore belongs to
                `pump`'s `finally` alone - one owner, one send, no race between
                two threads flushing the same batch.
                """
                while not finished.wait(LOG_FLUSH_INTERVAL):
                    flush()

            try:
                log_stream = _open_log_stream(cont, stream, tail)
                if stop.is_set():
                    # The client left while the daemon was still answering: do
                    # not leave a reader parked on a stream nobody reads.
                    _close_stream(log_stream)
                    return
                timer = threading.Thread(target=flusher, daemon=True)
                timer.start()
                try:
                    for line in log_stream:
                        if stop.is_set():
                            break
                        with lock:
                            pending.append(
                                line.decode("utf-8", errors="replace").rstrip("\n")
                            )
                            if len(pending) > LOG_MAX_PENDING_LINES:
                                # Drop-OLDEST, and count it so the client is told
                                # how much it missed: the newest lines are the
                                # ones a client that fell behind actually wants.
                                excess = len(pending) - LOG_MAX_PENDING_LINES
                                del pending[:excess]
                                counter["dropped"] += excess
                except Exception:
                    logger.debug("log stream reader stopped", exc_info=True)
            except Exception as e:
                # The stream could not be opened at all. Nothing has been sent
                # yet, so the receive loop below reports this instead of the
                # socket closing with zero frames - the silent close L-06
                # forbids. `stop` is deliberately NOT set here: it would make
                # the receive loop leave before it got to send the frame.
                failure.append(_safe_reason(e))
            finally:
                # Deterministic teardown: signal, let the timer thread finish
                # whatever flush it is in the middle of, then flush the tail
                # exactly once. The `is_alive()` guard matters: joining a thread
                # that was never started raises, and that must not cost us the
                # tail of the log. A stream that never opened has no timer and
                # an empty buffer, so there is nothing to flush.
                if timer is not None:
                    finished.set()
                    if timer.is_alive():
                        timer.join(timeout=LOG_FLUSH_INTERVAL * 5)
                    flush()
                    loop.call_soon_threadsafe(stop.set)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()

        # Stay responsive while the stream runs: wait for a client disconnect
        # with a bounded timeout instead of blocking on the log reader. The same
        # tick is where a producer that could not open the stream is noticed, so
        # the error frame below is sent at most LOG_POLL_INTERVAL late.
        while not stop.is_set():
            if failure:
                await _send_error_frame(ws, f"无法读取容器日志：{failure[0]}")
                break
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=LOG_POLL_INTERVAL)
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
        # Closes the underlying socket, unblocking the producer thread.
        _close_stream(log_stream)
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
    if not is_same_site(ws.headers.get("origin"), ws.headers.get("host")):
        logger.warning(
            "rejected cross-site exec websocket (origin=%r)", ws.headers.get("origin")
        )
        await ws.close(code=1008)
        return

    await ws.accept()
    raw = None
    stop = threading.Event()
    reader = None
    api = None
    exec_id = None
    try:
        client = get_docker_client()
        api = client.api
        try:
            cont = await asyncio.to_thread(client.containers.get, container)

            # Everything up to the first terminal byte happens here: nothing has
            # been written to the client yet, so any failure can still be
            # reported as a readable frame instead of a silent close.
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
        except docker.errors.NotFound:
            # Say *why* instead of closing silently: a zero-frame close is
            # indistinguishable from "the shell exited normally".
            await _send_error_frame(ws, f"no such container: {container}")
            return
        except docker.errors.APIError as e:
            # A docker failure other than "missing" - a container that is not
            # running fails right here, at exec_create with 409 - used to close
            # the socket with zero frames, so the user only ever saw "已断开".
            # Report the daemon's own words instead.
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 404:
                reason = f"no such container: {container}"
            else:
                reason = f"docker 守护进程错误：{_safe_reason(e)}"
            await _send_error_frame(ws, reason)
            return
        except docker.errors.DockerException as e:
            # Cannot talk to the daemon at all (socket missing, permission...).
            await _send_error_frame(ws, f"无法连接 docker 守护进程：{_safe_reason(e)}")
            return

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
