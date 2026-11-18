"""FastAPI Main Application Entrypoint."""

from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import logger
from app.core.database import init_db
from app.api.v1.router import api_v1_router 
from datetime import datetime, timezone 


from app.services.telegram.scheduler import (
    start_scanner_scheduler,
    stop_scanner_scheduler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info(f"Starting {settings.PROJECT_NAME} in [{settings.APP_ENV}] mode (MODE={settings.MODE})...")
    
    # Fail fast if MOCK provider is configured for LIVE mode
    if settings.MODE.lower() == "live" and settings.MARKET_DATA_PROVIDER.lower() == "mock":
        raise RuntimeError("FATAL: Cannot run in LIVE mode with MOCK market data provider.")
        
    init_db()

    # Persistent shared HTTP client — eliminates per-request TCP/TLS handshake overhead.
    # Providers receive this via dependency injection for high-frequency paths.
    app.state.http_client = httpx.AsyncClient(
        timeout=15.0,
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    )

    if settings.SCANNER_ENABLED:
        start_scanner_scheduler()
    else:
        logger.info("Automated market scanner disabled (SCANNER_ENABLED=False).")

    logger.info("Application startup complete.")
    yield
    logger.info("Application shutting down...")
    stop_scanner_scheduler()
    await app.state.http_client.aclose()
    logger.info("Application shutdown complete.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Forex Market Analysis, Market Structure, Liquidity Detection, and Signal Generation Engine",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(api_v1_router, prefix="/api")    


@app.get("/ping", tags=["health"])
def ping():
    """Ultra-lightweight keepalive endpoint for Render free tier."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}



@app.get("/")
def root():
    """Root landing endpoint."""
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_url": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
