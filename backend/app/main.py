from fastapi import FastAPI

from app.config import get_settings
from app.routers import containers as containers_router
from app.routers import images as images_router
from app.routers import networks as networks_router
from app.routers import volumes as volumes_router

app = FastAPI(title="docker-manager")


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(containers_router.router)
app.include_router(images_router.router)
app.include_router(networks_router.router)
app.include_router(volumes_router.router)