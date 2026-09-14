from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import containers as containers_router
from app.routers import files as files_router
from app.routers import images as images_router
from app.routers import networks as networks_router
from app.routers import volumes as volumes_router
from app.routers import ws as ws_router
from app.services.files import clear_tmp_dir
from app.services.security import is_same_site

# Methods a cross-site page can trigger without a CORS preflight. GET/HEAD are
# deliberately not guarded: they are not supposed to have side effects.
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(_app):
    clear_tmp_dir()
    yield


app = FastAPI(title="docker-manager", lifespan=lifespan)


@app.middleware("http")
async def cross_site_guard(request: Request, call_next):
    """Reject state-changing requests that a foreign page made the browser send.

    Binding to 127.0.0.1 does not stop this: the request really does come from
    the user's own machine. The Origin header does (see services/security.py).
    """
    if request.method.upper() in UNSAFE_METHODS and not is_same_site(
        request.headers.get("origin"), request.headers.get("host")
    ):
        return JSONResponse(
            {"detail": "cross-site request rejected (Origin not allowed)"},
            status_code=403,
        )
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(containers_router.router)
app.include_router(images_router.router)
app.include_router(networks_router.router)
app.include_router(volumes_router.router)
app.include_router(files_router.router)
app.include_router(ws_router.router)