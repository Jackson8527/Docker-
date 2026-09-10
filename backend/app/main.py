from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(title="docker-manager")


@app.get("/api/health")
def health():
    return {"status": "ok"}