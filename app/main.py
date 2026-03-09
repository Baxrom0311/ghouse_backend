# app.main.py
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ai_chat, auth, greenhouse, plant
from app.core.db import create_db_and_tables

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment]

mcp: Any | None = None
mcp_http_app = None


@asynccontextmanager
async def default_lifespan(app: FastAPI):
    create_db_and_tables()
    print("Database tables created/verified")
    yield
    print("Application shutting down")



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
    allow_origins=["*"],
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
