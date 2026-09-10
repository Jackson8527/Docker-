from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.routers import containers as containers_router
from app.routers import files as files_router
from app.routers import images as images_router
from app.routers import networks as networks_router
from app.routers import volumes as volumes_router
from app.routers import ws as ws_router
from app.services.files import clear_tmp_dir


@asynccontextmanager
async def lifespan(_app):
    clear_tmp_dir()
    yield


app = FastAPI(title="docker-manager", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(containers_router.router)
app.include_router(images_router.router)
app.include_router(networks_router.router)
app.include_router(volumes_router.router)
app.include_router(files_router.router)
app.include_router(ws_router.router)