import io
import os
import tarfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse

from app.services.docker import get_docker_client, extract_error
from app.services.files import get_tmp_dir

router = APIRouter(tags=["files"])


@router.post("/api/containers/{cid}/copy")
async def copy_into(cid: str, dest: str = Form(...), file: UploadFile = File(...)):
    tmp = get_tmp_dir()
    local = tmp / os.path.basename(file.filename)
    local.write_bytes(await file.read())
    try:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(local, arcname=os.path.basename(str(local)))
        get_docker_client().containers.get(cid).put_archive(dest, buf.getvalue())
        local.unlink(missing_ok=True)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))


@router.get("/api/containers/{cid}/copy")
def copy_out(cid: str, path: str = Query("/")):
    try:
        bits, _stat = get_docker_client().containers.get(cid).get_archive(path)
        return StreamingResponse(bits, media_type="application/x-tar")
    except Exception as e:
        raise HTTPException(500, extract_error(e))