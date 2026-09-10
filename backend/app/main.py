from fastapi import FastAPI

from app.config import get_settings
from app.routers import containers as containers_router

app = FastAPI(title="docker-manager")


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(containers_router.router)