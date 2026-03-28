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


from .routers import identities, sync, sessions, health as health_router  # noqa: E402

app.include_router(identities.router)
app.include_router(sync.router)
app.include_router(sessions.router)
app.include_router(health_router.router)


@app.get("/api/capabilities")
async def capabilities(authorization: str | None = None):
    from .auth import hash_token
    from .database import async_session_factory
    from .models import Identity
    from sqlalchemy import select

    base = {"mode": "server"}

    if authorization and authorization.startswith("Bearer "):
        token_h = hash_token(authorization[7:])
        async with async_session_factory() as db:
            result = await db.execute(
                select(Identity).where(Identity.token_hash == token_h)
            )
            ident = result.scalar_one_or_none()
            if ident and ident.enabled:
                base["identity"] = {
                    "name": ident.name,
                    "callSign": ident.call_sign,
                    "isAdmin": ident.is_admin,
                }
    return base
