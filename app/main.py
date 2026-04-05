# app.main.py
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import ai_chat, auth, greenhouse, plant
from app.core.config import configure_logging, settings
from app.core.db import create_db_and_tables, engine

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment]

configure_logging()

logger = logging.getLogger(__name__)
mcp: Any | None = None
mcp_http_app = None


@asynccontextmanager
async def default_lifespan(app: FastAPI):
    create_db_and_tables()
    logger.info("Database tables created/verified")
    yield
    logger.info("Application shutting down")



@asynccontextmanager
async def merged_lifespan(app: FastAPI):
    async with default_lifespan(app):
        yield


app = FastAPI(
    title="AgroAI Smart Greenhouse API System",
    description="Backend API for AgroAI Smart Greenhouse API System",
    version="0.1.0",
    lifespan=merged_lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix='/api')
app.include_router(greenhouse.router, prefix='/api')
app.include_router(plant.router, prefix='/api')
app.include_router(ai_chat.router, prefix='/api')
# app.include_router(chat.router)


if FastMCP is not None:
    mcp = FastMCP.from_fastapi(app)
    app.state.mcp = mcp
    mcp_http_app = mcp.http_app()
    app.mount("/mcp", mcp_http_app)


@app.get("/", tags=["[default]"])
def root():
    """Root endpoint."""
    return {
        "message": "AgroAI Smart Greenhouse API System",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["[default]"])
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/health/ready", tags=["[default]"])
def readiness_check():
    """Readiness check endpoint."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Database is not ready") from exc

    return {"status": "ready"}
