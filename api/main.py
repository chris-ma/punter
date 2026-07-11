"""
FastAPI application — serves race/runner data and live edge to the UI.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import races, runners

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Racing Edge API starting")
    yield
    log.info("Racing Edge API shutting down")


app = FastAPI(title="Racing Edge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(races.router, prefix="/races", tags=["races"])
app.include_router(runners.router, prefix="/runners", tags=["runners"])


@app.get("/health")
def health():
    return {"status": "ok"}
