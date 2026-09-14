import asyncio
import io
import os
import tarfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse

from app.services.docker import get_docker_client, extract_error
from app.services.files import get_tmp_dir

router = APIRouter(tags=["files"])


def _stage_and_push(cid: str, dest: str, local: Path, data: bytes) -> None:
    """Blocking half of the upload: write, pack, push. Runs in a worker thread."""
    local.write_bytes(data)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(local, arcname=local.name)
    get_docker_client().containers.get(cid).put_archive(dest, buf.getvalue())


@router.post("/api/containers/{cid}/copy")
async def copy_into(cid: str, dest: str = Form(...), file: UploadFile = File(...)):
    tmp = get_tmp_dir()
    local = tmp / os.path.basename(file.filename or "upload.bin")
    try:
        data = await file.read()
        # Writing the staging file, building the tar and pushing it to the
        # daemon are all blocking. A large upload used to run them on the single
        # event loop and freeze every request and websocket until it finished -
        # the same mechanism as the /ws/logs incident in R1.
        await asyncio.to_thread(_stage_and_push, cid, dest, local, data)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))
    finally:
        # Never leave a staging file behind; startup cleanup is only a backstop.
        local.unlink(missing_ok=True)


@router.get("/api/containers/{cid}/copy")
def copy_out(cid: str, path: str = Query("/")):
    try:
        bits, _stat = get_docker_client().containers.get(cid).get_archive(path)
        return StreamingResponse(bits, media_type="application/x-tar")
    except Exception as e:
        raise HTTPException(500, extract_error(e))