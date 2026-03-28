from contextlib import asynccontextmanager
import subprocess
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

logger = logging.getLogger("danflow")


def run_migrations():
    """Run alembic upgrade head using sync DB URL."""
    try:
        subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd="/app",
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("Database migrations complete")
    except subprocess.CalledProcessError as e:
        logger.error("Migration failed: %s", e.stderr)
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="Dan Flow Server", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/capabilities")
async def capabilities():
    return {"mode": "server"}
